#!/bin/sh
set -eu

key_file=${AW0_AUTHORIZED_KEYS_FILE:-$HOME/.ssh/id_ed25519.pub}
if [ ! -s "$key_file" ]; then
  echo "Public key not found: $key_file" >&2
  echo "Set AW0_AUTHORIZED_KEYS_FILE to an existing public key." >&2
  exit 1
fi

docker build \
  --tag ilosia-agent-workspace-aw0:0.1.0 \
  spikes/agent-workspace/image
k3d image import ilosia-agent-workspace-aw0:0.1.0 --cluster ilosia

kubectl create namespace aw0-workspace \
  --dry-run=client \
  --output=yaml | kubectl apply -f -
kubectl label namespace aw0-workspace \
  pod-security.kubernetes.io/enforce=restricted \
  pod-security.kubernetes.io/enforce-version=latest \
  --overwrite
if ! kubectl get secret aw0-authorized-keys --namespace aw0-workspace >/dev/null 2>&1; then
  kubectl create secret generic aw0-authorized-keys \
    --namespace aw0-workspace \
    --from-file=authorizedKeys="$key_file" \
    --dry-run=client \
    --output=yaml | kubectl apply -f -
fi
kubectl apply --filename spikes/agent-workspace/workspace.yaml
kubectl rollout status deployment/aw0-workspace \
  --namespace aw0-workspace \
  --timeout=5m

pod=$(kubectl get pod --namespace aw0-workspace \
  --selector app.kubernetes.io/name=aw0-workspace \
  --output jsonpath='{.items[0].metadata.name}')
kubectl exec --namespace aw0-workspace "$pod" -- \
  sh -c 'herdr --version && codex --version && git -C /workspace/repository status --short'

echo "AW0 workspace is ready at aw0-workspace.aw0-workspace.svc.cluster.local:2222."
