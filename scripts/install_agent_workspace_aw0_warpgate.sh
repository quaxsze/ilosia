#!/bin/sh
set -eu

kubectl create namespace warpgate --dry-run=client --output=yaml | kubectl apply -f -

if [ -n "${WARPGATE_AW0_ADMIN_PASSWORD:-}" ]; then
  kubectl create secret generic warpgate-aw0 \
    --namespace warpgate \
    --from-literal=adminPassword="$WARPGATE_AW0_ADMIN_PASSWORD" \
    --dry-run=client \
    --output=yaml | kubectl apply -f -
elif ! kubectl get secret warpgate-aw0 --namespace warpgate >/dev/null 2>&1; then
  echo "Export WARPGATE_AW0_ADMIN_PASSWORD for the first installation." >&2
  exit 1
fi

helm upgrade --install warpgate \
  oci://ghcr.io/warp-tech/helm-charts/warpgate \
  --version 0.2.0 \
  --namespace warpgate \
  --values spikes/agent-workspace/warpgate-values.yaml \
  --wait \
  --timeout 5m

kubectl wait --namespace warpgate \
  --for=condition=Ready pod \
  --selector=app.kubernetes.io/instance=warpgate \
  --timeout=180s

echo "Warpgate 0.30.2 is ready."
echo "Admin UI: kubectl port-forward --namespace warpgate service/warpgate 8888:8888"
