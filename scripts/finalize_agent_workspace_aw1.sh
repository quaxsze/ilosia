#!/bin/sh
set -eu

namespace=warpgate
deployment=$(kubectl get deployment warpgate --namespace "$namespace" --output=json)
printf '%s' "$deployment" | jq --exit-status '
  [.spec.template.spec.containers[].env[]?.valueFrom.secretKeyRef.name] |
  index("warpgate-secrets") != null
' >/dev/null
printf '%s' "$deployment" | jq --exit-status '
  [.spec.template.spec.containers[].env[]?.valueFrom.secretKeyRef.name] |
  index("warpgate-aw0") == null
' >/dev/null
kubectl rollout status deployment/warpgate --namespace "$namespace" --timeout=5m

for secret in warpgate-aw0 warpgate-aw0-api warpgate-aw0-config warpgate-aw0-oidc; do
  kubectl delete secret "$secret" --namespace "$namespace" --ignore-not-found
done
echo "PASS: obsolete AW0 Warpgate Secrets removed after the AW1 rollout."
