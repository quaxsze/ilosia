#!/bin/sh
set -eu

namespace=warpgate
keycloak_namespace=ilosia
public_host=${WARPGATE_PUBLIC_HOST:-warpgate.localhost}
public_port=${WARPGATE_PUBLIC_PORT:-8443}
client_id=${WARPGATE_OIDC_CLIENT_ID:-warpgate-aw0}
provider_name=${WARPGATE_OIDC_PROVIDER:-keycloak-aw0}
local_dir=${WARPGATE_LOCAL_DIR:-.local/warpgate}
tmp_dir=$(mktemp -d)
trap 'rm -rf "$tmp_dir"' EXIT INT TERM
umask 077

secret_value() {
  secret=$1
  key=$2
  kubectl get secret "$secret" --namespace "$namespace" \
    --output="go-template={{index .data \"$key\" | base64decode}}" 2>/dev/null
}

first_secret_value() {
  value=$(secret_value "$1" "$2" || true)
  if [ -z "$value" ]; then
    value=$(secret_value "$3" "$4" || true)
  fi
  [ -n "$value" ] || {
    echo "Missing $1/$2 and migration source $3/$4." >&2
    exit 1
  }
  printf '%s' "$value"
}

admin_password=$(first_secret_value warpgate-secrets adminPassword warpgate-aw0 adminPassword)
oidc_secret=$(first_secret_value warpgate-secrets oidcClientSecret warpgate-aw0-oidc clientSecret)
api_token=$(first_secret_value warpgate-secrets apiToken warpgate-aw0-api token)
encryption_key=$(secret_value warpgate-secrets encryptionKey || true)
if [ -z "$encryption_key" ]; then
  encryption_key=$(openssl rand -base64 32)
fi

kubectl create secret generic warpgate-secrets \
  --namespace "$namespace" \
  --from-literal=adminPassword="$admin_password" \
  --from-literal=oidcClientSecret="$oidc_secret" \
  --from-literal=apiToken="$api_token" \
  --from-literal=encryptionKey="$encryption_key" \
  --dry-run=client --output=yaml | kubectl apply -f - >/dev/null

if ! kubectl get secret warpgate-tls-ca --namespace "$namespace" >/dev/null 2>&1; then
  openssl req -x509 -newkey rsa:3072 -nodes -days 3650 \
    -subj '/CN=Ilosia local development CA' \
    -keyout "$tmp_dir/ca.key" -out "$tmp_dir/ca.crt" >/dev/null 2>&1
  kubectl create secret generic warpgate-tls-ca \
    --namespace "$namespace" \
    --from-file=ca.crt="$tmp_dir/ca.crt" \
    --from-file=ca.key="$tmp_dir/ca.key" \
    --dry-run=client --output=yaml | kubectl apply -f - >/dev/null
fi

secret_value warpgate-tls-ca ca.crt >"$tmp_dir/ca.crt"
secret_value warpgate-tls-ca ca.key >"$tmp_dir/ca.key"

public_keys=$(kubectl exec --namespace "$namespace" deployment/warpgate \
  --container warpgate -- warpgate client-keys 2>/dev/null | \
  awk '/^ssh-(ed25519|rsa) /' | jq --raw-input --slurp \
  'split("\n") | map(select(length > 0))')
[ "$public_keys" != "[]" ] || {
  echo "Warpgate did not return a client SSH key." >&2
  exit 1
}

if ! kubectl get secret warpgate-tls --namespace "$namespace" >/dev/null 2>&1; then
  openssl req -newkey rsa:3072 -nodes \
    -subj "/CN=$public_host" \
    -keyout "$tmp_dir/tls.key" -out "$tmp_dir/tls.csr" >/dev/null 2>&1
  cat >"$tmp_dir/tls.ext" <<EOF
subjectAltName=DNS:$public_host,DNS:warpgate.warpgate.svc.cluster.local
extendedKeyUsage=serverAuth
EOF
  openssl x509 -req -days 825 -sha256 \
    -in "$tmp_dir/tls.csr" \
    -CA "$tmp_dir/ca.crt" -CAkey "$tmp_dir/ca.key" -CAcreateserial \
    -extfile "$tmp_dir/tls.ext" -out "$tmp_dir/tls.crt" >/dev/null 2>&1
  kubectl create secret tls warpgate-tls \
    --namespace "$namespace" \
    --cert="$tmp_dir/tls.crt" --key="$tmp_dir/tls.key" \
    --dry-run=client --output=yaml | kubectl apply -f - >/dev/null
fi

mkdir -p "$local_dir"
cp "$tmp_dir/ca.crt" "$local_dir/ca.crt"
chmod 0644 "$local_dir/ca.crt"
kubectl create secret generic warpgate-ca \
  --namespace "$keycloak_namespace" \
  --from-file=ca.crt="$tmp_dir/ca.crt" \
  --from-literal=publicKeys="$public_keys" \
  --dry-run=client --output=yaml | kubectl apply -f - >/dev/null

api_token_base64=$(printf '%s' "$api_token" | base64 | tr -d '\n')
api_token_patch=$(jq --null-input --compact-output --arg value "$api_token_base64" \
  '{data:{WARPGATE_API_TOKEN:$value}}')
kubectl patch secret ilosia-secrets --namespace "$keycloak_namespace" \
  --type=merge --patch "$api_token_patch" >/dev/null

redirect_uri="https://$public_host:$public_port/@warpgate/api/sso/return"
web_origin="https://$public_host:$public_port"
backchannel_uri=https://warpgate.warpgate.svc.cluster.local:8888/@warpgate/api/sso/providers/$provider_name/backchannel-logout

keycloak_pod=$(kubectl get pod --namespace "$keycloak_namespace" \
  --selector app.kubernetes.io/name=keycloak \
  --field-selector=status.phase=Running \
  --output=jsonpath='{.items[0].metadata.name}')
[ -n "$keycloak_pod" ] || {
  echo "No running Keycloak Pod found." >&2
  exit 1
}
admin_username=$(kubectl get secret ilosia-secrets --namespace "$keycloak_namespace" \
  --output='go-template={{index .data "KEYCLOAK_ADMIN_USERNAME" | base64decode}}')
admin_password=$(kubectl get secret ilosia-secrets --namespace "$keycloak_namespace" \
  --output='go-template={{index .data "KEYCLOAK_ADMIN_PASSWORD" | base64decode}}')

kcadm() {
  kubectl exec --stdin --namespace "$keycloak_namespace" "$keycloak_pod" -- \
    /opt/keycloak/bin/kcadm.sh "$@" --no-config \
    --server http://127.0.0.1:8080 --realm master \
    --user "$admin_username" --password "$admin_password"
}

clients=$(kcadm get clients -r ilosia --query "clientId=$client_id")
client_uuid=$(printf '%s' "$clients" | jq --raw-output --arg client_id "$client_id" \
  '[.[] | select(.clientId == $client_id)] | if length == 1 then .[0].id else empty end')
[ -n "$client_uuid" ] || {
  echo "Expected one Keycloak client named $client_id." >&2
  exit 1
}

jq --null-input \
  --arg client_id "$client_id" \
  --arg secret "$oidc_secret" \
  --arg redirect_uri "$redirect_uri" \
  --arg web_origin "$web_origin" \
  --arg backchannel_uri "$backchannel_uri" \
  '{
    clientId: $client_id,
    name: "Warpgate",
    enabled: true,
    protocol: "openid-connect",
    publicClient: false,
    clientAuthenticatorType: "client-secret",
    secret: $secret,
    standardFlowEnabled: true,
    directAccessGrantsEnabled: false,
    serviceAccountsEnabled: false,
    redirectUris: [$redirect_uri],
    webOrigins: [$web_origin],
    attributes: {
      "backchannel.logout.url": $backchannel_uri,
      "backchannel.logout.session.required": "true",
      "backchannel.logout.revoke.offline.tokens": "true"
    }
  }' >"$tmp_dir/client.json"
kcadm update "clients/$client_uuid" -r ilosia --file - \
  <"$tmp_dir/client.json" >/dev/null

# shortcut: local Keycloak is reached through k3d's host gateway; production uses DNS.
cluster_name=${K3D_CLUSTER_NAME:-ilosia}
host_gateway=$(docker inspect "k3d-$cluster_name-server-0" | jq --exit-status --raw-output \
  '[.[0].NetworkSettings.Networks[].Gateway | select(test("^([0-9]{1,3}\\.){3}[0-9]{1,3}$"))] | first')
patch=$(jq --compact-output --null-input --arg ip "$host_gateway" \
  '{spec:{template:{spec:{hostAliases:[{ip:$ip,hostnames:["keycloak.localhost"]}]}}}}')
kubectl apply --filename gitops/applications/warpgate.yaml >/dev/null
kubectl patch deployment warpgate --namespace "$namespace" \
  --type=merge --patch "$patch" >/dev/null

cat <<EOF
AW1 prerequisites are ready.
CA certificate: $local_dir/ca.crt
Commit and push the GitOps changes, then wait for Argo CD to become Healthy.
EOF
