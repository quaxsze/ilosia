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
public_keys=$(kubectl get secret warpgate-ca --namespace ilosia \
  --output='go-template={{index .data "publicKeys" | base64decode}}')
printf '%s' "$public_keys" | jq --exit-status \
  'type == "array" and length > 0 and all(startswith("ssh-"))' >/dev/null || {
  echo "FAIL: ilosia/warpgate-ca does not contain Warpgate public keys." >&2
  exit 1
}
warpgate_token=$(kubectl get secret warpgate-secrets --namespace warpgate \
  --output='go-template={{index .data "apiToken" | base64decode}}')
ilosia_token=$(kubectl get secret ilosia-secrets --namespace ilosia \
  --output='go-template={{index .data "WARPGATE_API_TOKEN" | base64decode}}')
[ -n "$ilosia_token" ] && [ "$ilosia_token" = "$warpgate_token" ] || {
  echo "FAIL: Ilosia does not have the current Warpgate API token." >&2
  exit 1
}

encryption_key=$(kubectl get secret warpgate-secrets --namespace "$namespace" \
  --output='go-template={{index .data "encryptionKey" | base64decode}}')
key_bytes=$(printf '%s' "$encryption_key" | openssl base64 -d -A | wc -c | tr -d ' ')
[ "$key_bytes" = 32 ] || {
  echo "FAIL: WARPGATE_ENCRYPTION_KEY decodes to $key_bytes bytes, expected 32." >&2
  exit 1
}

deployment=$(kubectl get deployment warpgate --namespace "$namespace" --output=json)
if ! printf '%s' "$deployment" | jq --exit-status '
  [.spec.template.spec.containers[].env[]?.valueFrom.secretKeyRef.name] |
  index("warpgate-secrets") != null
' >/dev/null; then
  echo "FAIL: Warpgate does not reference warpgate-secrets." >&2
  exit 1
fi
if ! printf '%s' "$deployment" | jq --exit-status '
  [.spec.template.spec.containers[].env[]?.valueFrom.secretKeyRef.name] |
  index("warpgate-aw0") == null
' >/dev/null; then
  echo "FAIL: Warpgate still references an AW0 Secret." >&2
  exit 1
fi
kubectl rollout status deployment/warpgate --namespace "$namespace" --timeout=5m

if ! kubectl get ingress warpgate --namespace "$namespace" --output=json | \
  jq --exit-status '
    .spec.ingressClassName == "nginx" and
    .spec.rules[0].host == "warpgate.localhost" and
    .spec.tls[0].secretName == "warpgate-tls"
  ' >/dev/null; then
  echo "FAIL: Warpgate Ingress or TLS does not match the AW1 values." >&2
  exit 1
fi
if ! kubectl get deployment keycloak --namespace ilosia --output=json | \
  jq --exit-status '
    [.spec.template.spec.containers[].env[]? | select(.name == "KC_TRUSTSTORE_PATHS")] | length == 1
  ' >/dev/null; then
  echo "FAIL: Keycloak has not mounted the Warpgate CA yet." >&2
  exit 1
fi

test -s "$ca_file" || {
  echo "FAIL: CA bundle not found at $ca_file." >&2
  exit 1
}
./scripts/start_agent_workspace_aw1_https_proxy.sh >/dev/null
curl --fail --silent --show-error \
  --connect-timeout 5 --max-time 20 \
  --cacert "$ca_file" \
  "https://warpgate.localhost:$public_port/@warpgate/" >/dev/null

echo "PASS: Agent Workspace AW1 secrets, encryption, TLS and GitOps state are healthy."
