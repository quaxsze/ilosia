#!/bin/sh
set -eu

namespace=${AW2_NAMESPACE:-aw2-workspace}
release=${AW2_RELEASE:-aw2-workspace}
selector="app.kubernetes.io/instance=$release"
marker=/workspace/home/.aw2-persistence-check
test_name='AW2 Persistence Test'

pod=$(kubectl get pod --namespace "$namespace" \
  --selector "$selector" --field-selector=status.phase=Running \
  --output=jsonpath='{.items[0].metadata.name}')
[ -n "$pod" ] || {
  echo "No running Agent Workspace Pod found in $namespace." >&2
  exit 1
}

kubectl wait --namespace "$namespace" --for=condition=Ready "pod/$pod" --timeout=2m
original_name=$(kubectl exec --namespace "$namespace" "$pod" -- \
  git config --global user.name)
host_key=$(kubectl exec --namespace "$namespace" "$pod" -- \
  sha256sum /workspace/ssh-host-keys/ssh_host_ed25519_key.pub | awk '{print $1}')

kubectl exec --namespace "$namespace" "$pod" -- sh -c \
  'printf %s persistence-ok >"$1" && git config --global user.name "$2"' \
  sh "$marker" "$test_name"

kubectl delete pod --namespace "$namespace" "$pod" --wait=true >/dev/null
kubectl wait --namespace "$namespace" --for=condition=Ready pod \
  --selector "$selector" --timeout=5m

new_pod=$(kubectl get pod --namespace "$namespace" \
  --selector "$selector" --field-selector=status.phase=Running \
  --output=jsonpath='{.items[0].metadata.name}')
[ "$new_pod" != "$pod" ] || {
  echo "The Agent Workspace Pod was not recreated." >&2
  exit 1
}

kubectl exec --namespace "$namespace" "$new_pod" -- sh -c '
  test "$(cat "$1")" = persistence-ok
  test -d /workspace/repository/.git
  test "$(git config --global user.name)" = "$2"
  test "$NPM_CONFIG_PREFIX" = /workspace/home/.local
  test "$UV_TOOL_BIN_DIR" = /workspace/home/.local/bin
  test "$MISE_DATA_DIR" = /workspace/home/.local/share/mise
  herdr --version
  codex --version
  uv --version
  mise --version
' sh "$marker" "$test_name"

new_host_key=$(kubectl exec --namespace "$namespace" "$new_pod" -- \
  sha256sum /workspace/ssh-host-keys/ssh_host_ed25519_key.pub | awk '{print $1}')
[ "$new_host_key" = "$host_key" ] || {
  echo "The SSH host key changed after Pod recreation." >&2
  exit 1
}

kubectl exec --namespace "$namespace" "$new_pod" -- \
  git config --global user.name "$original_name"
kubectl exec --namespace "$namespace" "$new_pod" -- rm -f "$marker"

./scripts/check_agent_workspace_aw0_egress.sh "$namespace" "$selector"

echo 'PASS: Agent Workspace AW2 tools, repository, Git identity, PVC and SSH host key persist across Pod recreation.'
