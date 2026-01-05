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

apk add --no-cache jq curl >/dev/null

echo "Initializing Vault..."
vault operator init -key-shares=5 -key-threshold=3 -format=json > /tmp/init.json || true


echo "Waiting 5 secondes for leader stabilize..."
sleep 5

echo "Unsealing Vault pods..."
UNSEAL_KEYS=$(jq -r '.unseal_keys_b64[0:3][]' /tmp/init.json)
for i in 0 1 2; do
  POD_ADDR="http://vault-$i.vault-internal.vault.svc.cluster.local:8200"
  for key in $UNSEAL_KEYS; do
    VAULT_ADDR="$POD_ADDR" vault operator unseal "$key" || true
  done
done

echo "Joining raft followers..."
for i in 1 2; do
  POD_ADDR="http://vault-$i.vault-internal.vault.svc.cluster.local:8200"
  VAULT_ADDR="$POD_ADDR" vault operator raft join "$LEADER_ADDR" || true
done

echo "Bootstrap complete!"
cat /tmp/init.json || true
"""]
                }]
            }
        }
    }
)

