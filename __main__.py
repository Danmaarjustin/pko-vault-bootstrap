import pulumi
from pulumi_kubernetes.batch.v1 import Job

# --- Pulumi Config ---
config = pulumi.Config("vault")
vault_addr = config.require("address")  # bv http://vault-internal.vault.svc:8200
pod_count = config.get_int("pod_count") or 3  # default 3 pods

# --- Kubernetes Job ---
bootstrap_job = Job(
    "vault-bootstrap",
    spec={
        "backoffLimit": 5,
        "template": {
            "spec": {
                "restartPolicy": "OnFailure",
                "containers": [{
                    "name": "bootstrap",
                    "image": "hashicorp/vault:1.20.1",
                    "command": ["/bin/sh", "-c"],
                    "args": [f"""
set -e
export VAULT_ADDR={vault_addr}

# Add tools
apk add --no-cache jq curl >/dev/null

# Check if Vault is already initialized
if vault status -format=json | jq -e '.initialized == true'; then
  echo "Vault already initialized"
  exit 0
fi

echo "Initializing Vault..."
vault operator init -key-shares=5 -key-threshold=3 -format=json > /tmp/init.json

# Unseal all Vault pods
for i in $(seq 0 {pod_count_minus_one}); do
  for key in $(jq -r '.unseal_keys_b64[0:3][]' /tmp/init.json); do
    VAULT_ADDR=http://vault-$i.vault-internal.vault.svc:8200 vault operator unseal "$key"
  done
done

# Raft join followers (skip 0 because it's the leader)
for i in $(seq 1 {pod_count_minus_one}); do
  VAULT_ADDR=http://vault-$i.vault-internal.vault.svc:8200 vault operator raft join {vault_addr}
done

echo "Vault bootstrap complete. Keys:"
cat /tmp/init.json
""".replace("{pod_count_minus_one}", str(pod_count-1))]
                }]
            }
        }
    }
)

pulumi.export("bootstrap_job_name", bootstrap_job.metadata["name"])

