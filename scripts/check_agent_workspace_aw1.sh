#!/bin/sh
set -eu

namespace=warpgate
ca_file=${WARPGATE_CA_BUNDLE:-.local/warpgate/ca.crt}
public_port=${WARPGATE_PUBLIC_PORT:-8443}

for application in ilosia warpgate; do
  state=$(kubectl get application "$application" --namespace argocd \
    --output=jsonpath='{.status.sync.status}/{.status.health.status}')
  [ "$state" = Synced/Healthy ] || {
    echo "FAIL: Argo CD application $application is $state." >&2
    exit 1
  }
done

for secret in warpgate-secrets warpgate-tls warpgate-tls-ca; do
  kubectl get secret "$secret" --namespace "$namespace" >/dev/null
done
kubectl get secret warpgate-ca --namespace ilosia >/dev/null

encryption_key=$(kubectl get secret warpgate-secrets --namespace "$namespace" \
  --output='go-template={{index .data "encryptionKey" | base64decode}}')
key_bytes=$(printf '%s' "$encryption_key" | openssl base64 -d -A | wc -c | tr -d ' ')
[ "$key_bytes" = 32 ] || {
  echo "FAIL: WARPGATE_ENCRYPTION_KEY decodes to $key_bytes bytes, expected 32." >&2
  exit 1
}

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

kubectl get ingress warpgate --namespace "$namespace" --output=json | \
  jq --exit-status '
    .spec.ingressClassName == "nginx" and
    .spec.rules[0].host == "warpgate.localhost" and
    .spec.tls[0].secretName == "warpgate-tls"
  ' >/dev/null
kubectl get deployment keycloak --namespace ilosia --output=json | \
  jq --exit-status '
    [.spec.template.spec.containers[].env[]? | select(.name == "KC_TRUSTSTORE_PATHS")] | length == 1
  ' >/dev/null

test -s "$ca_file" || {
  echo "FAIL: CA bundle not found at $ca_file." >&2
  exit 1
}
./scripts/start_agent_workspace_aw1_https_proxy.sh >/dev/null
curl --fail --silent --show-error \
  --cacert "$ca_file" \
  "https://warpgate.localhost:$public_port/@warpgate/" >/dev/null

echo "PASS: Agent Workspace AW1 secrets, encryption, TLS and GitOps state are healthy."
