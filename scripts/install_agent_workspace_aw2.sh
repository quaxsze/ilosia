#!/bin/sh
set -eu

repository_url=${1:-https://github.com/quaxsze/ilosia.git}
cluster_name=${K3D_CLUSTER_NAME:-ilosia}
namespace=${AW2_NAMESPACE:-aw2-workspace}
release=${AW2_RELEASE:-aw2-workspace}
image=${AW2_IMAGE:-ilosia-agent-workspace:dev}
key_file=$(mktemp)
trap 'rm -f "$key_file"' EXIT INT TERM

docker build --tag "$image" images/agent-workspace
k3d image import "$image" --cluster "$cluster_name"

kubectl create namespace "$namespace" --dry-run=client --output=yaml | \
  kubectl apply -f - >/dev/null
kubectl label namespace "$namespace" \
  pod-security.kubernetes.io/enforce=restricted \
  pod-security.kubernetes.io/enforce-version=latest \
  --overwrite >/dev/null

kubectl exec --namespace warpgate deployment/warpgate -- \
  warpgate client-keys 2>/dev/null | \
  awk '/^ssh-ed25519 / {print; exit}' >"$key_file"
grep -Eq '^ssh-ed25519 ' "$key_file" || {
  echo "Warpgate did not return an Ed25519 client key." >&2
  exit 1
}

image_repository=${image%:*}
image_tag=${image##*:}
helm upgrade --install "$release" charts/agent-workspace \
  --namespace "$namespace" \
  --set-string "image.repository=$image_repository" \
  --set-string "image.tag=$image_tag" \
  --set-string image.pullPolicy=Never \
  --set-string "repository.url=$repository_url" \
  --set-string "git.userName=${AW2_GIT_USER_NAME:-AW2 Developer}" \
  --set-string "git.userEmail=${AW2_GIT_USER_EMAIL:-aw2@ilosia.invalid}" \
  --set-file "warpgate.publicKeys[0]=$key_file" \
  --wait --timeout 5m

WARPGATE_TARGET_NAME="$release" \
WARPGATE_ROLE_NAME="$release" \
WARPGATE_TARGET_HOST="$release.$namespace.svc.cluster.local" \
WARPGATE_TARGET_DESCRIPTION='Local Agent Workspace AW2' \
WARPGATE_SSO_USERNAME="${AW2_SSO_USERNAME:-alos}" \
  ./scripts/configure_agent_workspace_aw0_warpgate.sh

pod=$(kubectl get pod --namespace "$namespace" \
  --selector "app.kubernetes.io/instance=$release" \
  --field-selector=status.phase=Running \
  --output=jsonpath='{.items[0].metadata.name}')
kubectl exec --namespace "$namespace" "$pod" -- \
  sh -c 'herdr --version; codex --version; uv --version; mise --version; git -C /workspace/repository status --short'

cat <<EOF
PASS: Agent Workspace AW2 is ready.
SSH target: ${AW2_SSO_USERNAME:-alos}:$release@127.0.0.1 port 2222
EOF
