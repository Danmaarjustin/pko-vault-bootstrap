import pulumi
from pulumi_kubernetes.batch.v1 import Job

# --- Pulumi config ---
config = pulumi.Config("vault")
pod_count = config.get_int("pod_count") or 3

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
                    "args": ["""
set -euo pipefail

LEADER_ADDR="http://vault-0.vault-internal.vault.svc.cluster.local:8200"
export VAULT_ADDR="$LEADER_ADDR"

apk add --no-cache jq >/dev/null

echo "Initializing Vault (leader)..."
vault operator init -key-shares=5 -key-threshold=3 -format=json > /tmp/init.json || true

UNSEAL_KEYS=$(jq -r '.unseal_keys_b64[0:3][]' /tmp/init.json)

echo "Unsealing leader..."
for key in $UNSEAL_KEYS; do
  vault operator unseal "$key" || true
done

echo "Joining raft followers..."
for i in 1 2; do
  VAULT_ADDR="http://vault-$i.vault-internal.vault.svc.cluster.local:8200" \
    vault operator raft join "$LEADER_ADDR" || true
done

echo "Waiting for raft state to propagate..."
sleep 5

echo "Unsealing followers..."
for i in 1 2; do
  POD_ADDR="http://vault-$i.vault-internal.vault.svc.cluster.local:8200"
  for key in $UNSEAL_KEYS; do
    VAULT_ADDR="$POD_ADDR" vault operator unseal "$key" || true
  done
done

echo "Bootstrap complete"
cat /tmp/init.json
"""]
                }]
            }
        }
    }
)

