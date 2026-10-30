#!/bin/sh
set -eu

cluster_name=${K3D_CLUSTER_NAME:-ilosia}
expected_context="k3d-$cluster_name"
missing=false

for command_name in kubectl helm k3d docker jq ssh curl herdr codex; do
  if ! command -v "$command_name" >/dev/null 2>&1; then
    echo "MISSING: $command_name" >&2
    missing=true
  fi
done

if [ "$missing" = true ]; then
  echo "Install the missing commands, then rerun this preflight." >&2
  exit 1
fi

echo "AW0 preflight"
echo "--------------"
printf 'Herdr:     '
herdr --version
printf 'Codex:     '
codex --version
printf 'Helm:      '
helm version --short
printf 'kubectl:   '
kubectl version --client --output=yaml | awk '/gitVersion:/ {print $2; exit}'
printf 'k3d:       '
k3d version | awk 'NR == 1 {print $3}'
printf 'Context:   '
current_context=$(kubectl config current-context)
echo "$current_context"

if [ "$current_context" != "$expected_context" ]; then
  echo "Expected context $expected_context, got $current_context." >&2
  exit 1
fi

kubectl get --raw=/readyz >/dev/null
not_ready=$(kubectl get nodes --no-headers | awk '$2 != "Ready" {print $1}')
if [ -n "$not_ready" ]; then
  echo "Nodes not ready: $not_ready" >&2
  exit 1
fi

for namespace in ilosia nginx-ingress; do
  kubectl get namespace "$namespace" >/dev/null
done

if ! kubectl get deployment --namespace ilosia keycloak >/dev/null 2>&1; then
  echo "MISSING: deployment/keycloak in namespace ilosia" >&2
  exit 1
fi

load_balancer="k3d-$cluster_name-serverlb"
if ! docker port "$load_balancer" 2222/tcp 2>/dev/null | grep -q ':2222$'; then
  echo "NOTICE: $load_balancer does not publish host port 2222."
  echo "AW0 will use the disposable Docker proxy; native mapping remains deferred."
fi

echo "PASS: tools, cluster and Keycloak are ready for AW0."
echo "Next: follow spikes/agent-workspace/AW0_REPORT.md."
