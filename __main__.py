import pulumi
from pulumi_kubernetes.batch.v1 import Job

# --- Pulumi config ---
config = pulumi.Config("vault")
vault_addr = config.require("address")
pod_count = config.get_int("pod_count") or 3
pod_count_minus_one = pod_count - 1

# --- Job ---
bootstrap_job = Job(
    "vault-bootstrap",
    spec={
        "backoffLimit": 5,
        "template": {
            "spec": {
                "restartPolicy": "OnFailure",
                "containers": [{
                    "name": "bootstrap",
                    "image": "hashicorp/vault:1.15",
                    "command": ["/bin/sh", "-c"],
                    "args": [f"""
set -euo pipefail

LEADER_ADDR="http://vault-0.vault-internal.vault.svc.cluster.local:8200"
export VAULT_ADDR="$LEADER_ADDR"

apk add --no-cache jq curl >/dev/null

# Wacht tot Vault API reageert
until curl -fsS "$VAULT_ADDR/v1/sys/health?standbyok=true&sealedcode=200&uninitcode=200" >/dev/null; do
  echo "Vault not ready yet, retrying..."
  sleep 2
done

echo "Vault leader API is up!"

# Wacht tot Vault status geen error geeft
while true; do
  HEALTH=$(curl -fsS "$VAULT_ADDR/v1/sys/health?standbyok=true&sealedcode=200&uninitcode=200" 2>/dev/null || echo '{{}}')
  if echo "$HEALTH" | jq -e '.initialized != null' >/dev/null 2>&1; then
    break
  fi
  echo "Vault leader API not ready yet..."
  sleep 2
done

echo "Initializing Vault on vault-0"
vault operator init \
  -key-shares=5 \
  -key-threshold=3 \
  -format=json > /tmp/init.json

UNSEAL_KEYS=$(jq -r '.unseal_keys_b64[0:3][]' /tmp/init.json)

for i in 0 1 2; do
  POD_ADDR="http://vault-$i.vault-internal.vault.svc.cluster.local:8200"
  for key in $UNSEAL_KEYS; do
    VAULT_ADDR="$POD_ADDR" vault operator unseal "$key"
  done
done

echo "Joining raft followers"
VAULT_ADDR="http://vault-1.vault-internal.vault.svc.cluster.local:8200" \
  vault operator raft join "$LEADER_ADDR"

VAULT_ADDR="http://vault-2.vault-internal.vault.svc.cluster.local:8200" \
  vault operator raft join "$LEADER_ADDR"

echo "Bootstrap complete"
cat /tmp/init.json
"""]
                }]
            }
        }
    }
)
