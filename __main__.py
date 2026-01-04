import pulumi
from pulumi_kubernetes.batch.v1 import Job

# --- Pulumi config ophalen ---
config = pulumi.Config("vault")
vault_addr = config.require("address")  # haalt vault:address op uit Pulumi config

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
set -e
export VAULT_ADDR={vault_addr}

apk add --no-cache jq curl >/dev/null

if vault status -format=json | jq -e '.initialized == true'; then
  echo "Vault already initialized"
  exit 0
fi

echo "Initializing Vault"
vault operator init -key-shares=5 -key-threshold=3 -format=json > /tmp/init.json

echo "Unsealing all pods"
for i in 0 1 2; do
  for key in $(jq -r '.unseal_keys_b64[0:3][]' /tmp/init.json); do
    VAULT_ADDR=http://vault-$i.vault.svc:8200 vault operator unseal "$key"
  done
done

echo "Joining raft followers"
VAULT_ADDR=http://vault-1.vault.svc:8200 vault operator raft join {vault_addr}
VAULT_ADDR=http://vault-2.vault.svc:8200 vault operator raft join {vault_addr}

cat /tmp/init.json
"""]
                }]
            }
        }
    }
)

