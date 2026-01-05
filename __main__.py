import pulumi
from pulumi_kubernetes.batch.v1 import Job

config = pulumi.Config("vault")
vault_addr = config.require("address")
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

echo "Checking Vault initialization..."
STATUS=$(vault status -format=json)
if echo "$STATUS" | jq -e '.initialized == true' >/dev/null; then
  echo "Vault already initialized, skipping init"
else
  echo "Initializing Vault on vault-0"
  vault operator init -key-shares=5 -key-threshold=3 -format=json > /tmp/init.json
  echo "Storing keys in Kubernetes Secret..."
  kubectl create secret generic vault-init -n pulumi-kubernetes-operator --from-file=/tmp/init.json || true
fi

# Haal unseal keys uit Secret als init.json ontbreekt
if [ ! -f /tmp/init.json ]; then
  echo "Fetching existing unseal keys from Secret..."
  kubectl get secret vault-init -n pulumi-kubernetes-operator -o jsonpath='{.data.init\.json}' | base64 -d > /tmp/init.json
fi

# Unseal alle nodes
UNSEAL_KEYS=$(jq -r '.unseal_keys_b64[0:3][]' /tmp/init.json)
for i in $(seq 0 $((pod_count-1))); do
  POD_ADDR="http://vault-$i.vault-internal.vault.svc.cluster.local:8200"
  for key in $UNSEAL_KEYS; do
    echo "Unsealing $POD_ADDR"
    VAULT_ADDR="$POD_ADDR" vault operator unseal "$key" || true
  done
done

# Join raft followers
for i in $(seq 1 $((pod_count-1))); do
  POD_ADDR="http://vault-$i.vault-internal.vault.svc.cluster.local:8200"
  echo "Joining $POD_ADDR to leader $LEADER_ADDR"
  VAULT_ADDR="$POD_ADDR" vault operator raft join "$LEADER_ADDR" || true
done

echo "Bootstrap complete"
cat /tmp/init.json || true
"""]
                }]
            }
        }
    }
)

