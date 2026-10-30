#!/bin/sh
set -eu

if [ "$#" -ne 1 ]; then
  echo "Usage: $0 <keycloak-username>" >&2
  exit 2
fi

username=$1
namespace=warpgate
keycloak_namespace=ilosia
api_url=https://127.0.0.1:18888/@warpgate/admin/api/sessions
token=$(kubectl get secret warpgate-aw0-api --namespace "$namespace" \
  --output='go-template={{index .data "token" | base64decode}}')
port_forward_log=$(mktemp)
sessions_file=$(mktemp)
cleanup() {
  kill "${port_forward_pid:-}" 2>/dev/null || true
  wait "${port_forward_pid:-}" 2>/dev/null || true
  rm -f "$port_forward_log" "$sessions_file"
}
trap cleanup EXIT INT TERM

kubectl port-forward --namespace "$namespace" service/warpgate 18888:8888 \
  >"$port_forward_log" 2>&1 &
port_forward_pid=$!

attempt=0
until curl --insecure --silent --fail --max-time 1 \
  https://127.0.0.1:18888/@warpgate/api/info >/dev/null 2>&1; do
  attempt=$((attempt + 1))
  if [ "$attempt" -ge 50 ] || ! kill -0 "$port_forward_pid" 2>/dev/null; then
    echo "Warpgate port-forward did not become ready:" >&2
    cat "$port_forward_log" >&2
    exit 1
  fi
  sleep 0.2
done

active_sessions() {
  curl --insecure --silent --show-error --fail --max-time 10 \
    --header "x-warpgate-token: $token" "$api_url" >"$sessions_file"
  jq --arg username "$username" \
    '[.. | objects | select(
      .username? == $username and
      ((.protocol? // "") | ascii_upcase) == "SSH" and
      .ended? == null
    )] | length' "$sessions_file"
}

logout_diagnostics() {
  echo "--- Keycloak logout diagnostics ---" >&2
  kubectl logs --namespace "$keycloak_namespace" deployment/keycloak --since=2m 2>&1 |
    grep -Ei 'backchannel|logout|warpgate|error|exception|ssl|certificate' |
    tail -n 80 >&2 || true
  echo "--- Warpgate logout diagnostics ---" >&2
  kubectl logs --namespace "$namespace" deployment/warpgate --since=2m 2>&1 |
    grep -Ei 'backchannel|logout|error|warn|token' |
    tail -n 80 >&2 || true
}

before=$(active_sessions)
if [ "$before" -lt 1 ]; then
  cat >&2 <<EOF
No active SSH session exists for $username.
Start one in another terminal and approve it through Keycloak:
  ssh -p 2222 -o PreferredAuthentications=keyboard-interactive -o PubkeyAuthentication=no -o PasswordAuthentication=no '$username:aw0-workspace@127.0.0.1' 'sleep 600'
Then rerun this command while that SSH process is still connected.
EOF
  exit 1
fi

keycloak_pod=$(kubectl get pod --namespace "$keycloak_namespace" \
  --selector app.kubernetes.io/name=keycloak \
  --field-selector=status.phase=Running \
  --output=jsonpath='{.items[0].metadata.name}')
admin_username=$(kubectl get secret ilosia-secrets --namespace "$keycloak_namespace" \
  --output='go-template={{with index .data "KEYCLOAK_ADMIN_USERNAME"}}{{. | base64decode}}{{end}}')
admin_username=${admin_username:-admin}
admin_password=$(kubectl get secret ilosia-secrets --namespace "$keycloak_namespace" \
  --output='go-template={{index .data "KEYCLOAK_ADMIN_PASSWORD" | base64decode}}')

kcadm() {
  kubectl exec --stdin --namespace "$keycloak_namespace" "$keycloak_pod" -- \
    /opt/keycloak/bin/kcadm.sh "$@" \
    --no-config --server http://127.0.0.1:8080 --realm master \
    --user "$admin_username" --password "$admin_password"
}

if ! kcadm get realms/master >/dev/null; then
  echo "Keycloak rejected the administrator credentials." >&2
  exit 1
fi
users=$(kcadm get users -r ilosia --query "username=$username")
user_id=$(printf '%s' "$users" | jq --exit-status --raw-output --arg username "$username" \
  '[.[] | select(.username == $username)] | if length == 1 then .[0].id else empty end') || {
  echo "Expected exactly one Keycloak user named $username." >&2
  exit 1
}

started_at=$(date +%s)
kcadm create "users/$user_id/logout" -r ilosia \
  -s realm=ilosia -s "user=$user_id" >/dev/null

while [ "$(active_sessions)" -ne 0 ]; do
  if [ $(($(date +%s) - started_at)) -ge 20 ]; then
    echo "FAIL: Keycloak logout did not close the Warpgate SSH session within 20 seconds." >&2
    logout_diagnostics
    exit 1
  fi
  sleep 1
done

delay=$(($(date +%s) - started_at))
echo "PASS: Keycloak back-channel logout closed $before Warpgate SSH session(s) in ${delay}s."
