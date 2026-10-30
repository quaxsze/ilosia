#!/bin/sh
set -eu

namespace=warpgate
target_name=${WARPGATE_TARGET_NAME:-aw0-workspace}
role_name=${WARPGATE_ROLE_NAME:-$target_name}
target_host=${WARPGATE_TARGET_HOST:-aw0-workspace.aw0-workspace.svc.cluster.local}
target_description=${WARPGATE_TARGET_DESCRIPTION:-Local Agent Workspace AW0}
sso_username=${WARPGATE_SSO_USERNAME:-${WARPGATE_AW0_SSO_USERNAME:-}}
api_host=warpgate.warpgate.svc.cluster.local
api_url=https://$api_host:18888/@warpgate/admin/api
ca_file=${WARPGATE_CA_BUNDLE:-.local/warpgate/ca.crt}
token=${WARPGATE_AW0_API_TOKEN:-}

if [ -z "$token" ] && kubectl get secret warpgate-secrets --namespace "$namespace" >/dev/null 2>&1; then
  token=$(kubectl get secret warpgate-secrets --namespace "$namespace" \
    --output='go-template={{index .data "apiToken" | base64decode}}')
elif [ -z "$token" ] && kubectl get secret warpgate-aw0-api --namespace "$namespace" >/dev/null 2>&1; then
  token=$(kubectl get secret warpgate-aw0-api --namespace "$namespace" \
    --output='go-template={{index .data "token" | base64decode}}')
fi

if [ -z "$token" ]; then
  cat >&2 <<'EOF'
Warpgate needs a one-time API token to automate its administration.

1. Run: kubectl port-forward --namespace warpgate service/warpgate 8888:8888
2. Open: https://localhost:8888/@warpgate
3. Log in as the local user "admin" (check the name in the top-right), open
   the user menu, then API tokens, and create a fresh, non-expired token.
4. Run:
     read -s WARPGATE_AW0_API_TOKEN
     export WARPGATE_AW0_API_TOKEN
     ./scripts/setup_agent_workspace_aw0.sh

The next runs reuse the token stored in the local Kubernetes Secret.
EOF
  exit 2
fi

warpgate_curl() {
  if test -s "$ca_file"; then
    curl --cacert "$ca_file" --resolve "$api_host:18888:127.0.0.1" "$@"
  else
    # shortcut: AW0 uses only a loopback port-forward until AW1 creates the CA bundle.
    curl --insecure --resolve "$api_host:18888:127.0.0.1" "$@"
  fi
}

port_forward_log=$(mktemp)
api_response=$(mktemp)
kubectl port-forward --namespace "$namespace" service/warpgate 18888:8888 \
  >"$port_forward_log" 2>&1 &
port_forward_pid=$!
trap 'kill "$port_forward_pid" 2>/dev/null || true; wait "$port_forward_pid" 2>/dev/null || true; rm -f "$port_forward_log" "$api_response"' EXIT INT TERM

attempt=0
until warpgate_curl --silent --fail --max-time 1 \
  "https://$api_host:18888/@warpgate/api/info" >/dev/null 2>&1; do
  attempt=$((attempt + 1))
  if [ "$attempt" -ge 50 ] || ! kill -0 "$port_forward_pid" 2>/dev/null; then
    echo "Warpgate port-forward did not become ready:" >&2
    cat "$port_forward_log" >&2
    exit 1
  fi
  sleep 0.2
done

api_request() {
  method=$1
  path=$2
  body=${3-}
  : >"$api_response"
  if [ -n "$body" ]; then
    status=$(warpgate_curl --silent --show-error --max-time 10 \
      --request "$method" \
      --header "x-warpgate-token: $token" \
      --header 'content-type: application/json' \
      --data "$body" \
      --output "$api_response" \
      --write-out '%{http_code}' \
      "$api_url$path") || status=000
  else
    status=$(warpgate_curl --silent --show-error --max-time 10 \
      --request "$method" \
      --header "x-warpgate-token: $token" \
      --output "$api_response" \
      --write-out '%{http_code}' \
      "$api_url$path") || status=000
  fi

  case "$status" in
    2??) cat "$api_response" ;;
    *)
      echo "Warpgate API $method $path failed (HTTP $status):" >&2
      cat "$api_response" >&2
      return 1
      ;;
  esac
}

api_get() {
  api_request GET "$1"
}

api_write() {
  api_request "$@"
}

exact_id() {
  field=$1
  value=$2
  jq --exit-status --raw-output --arg field "$field" --arg value "$value" \
    '[.[] | select(.[$field] == $value)] | if length == 1 then .[0].id else empty end'
}

users=$(api_get '/users?search=admin') || exit 1
admin_id=$(printf '%s' "$users" | exact_id username admin) || {
  echo "Expected exactly one Warpgate user named admin." >&2
  exit 1
}
admin_body=$(printf '%s' "$users" | jq --compact-output --exit-status \
  '.[] | select(.username == "admin") | . as $user |
  {
    username,
    description: (.description // ""),
    credential_policy: ((.credential_policy // {}) + {ssh: ["WebUserApproval"]})
  } + ($user | {rate_limit_bytes_per_second, allowed_ip_ranges} |
    with_entries(select(.value != null)))')
api_write PUT "/users/$admin_id" "$admin_body" >/dev/null
api_get "/users/$admin_id" | jq --exit-status \
  '.credential_policy.ssh == ["WebUserApproval"]' >/dev/null || {
  echo "Warpgate did not persist browser approval as the admin SSH policy." >&2
  exit 1
}

roles=$(api_get "/roles?search=$role_name")
role_id=$(printf '%s' "$roles" | exact_id name "$role_name") || role_id=
if [ -z "$role_id" ]; then
  role_id=$(api_write POST /roles \
    "$(jq --compact-output --null-input --arg name "$role_name" \
      --arg description "$target_description" \
      '{name: $name, description: $description}')" | jq --exit-status --raw-output '.id')
fi

target_body=$(jq --compact-output --null-input \
  --arg name "$target_name" \
  --arg host "$target_host" \
  --arg description "$target_description" \
  '{
    name: $name,
    description: $description,
    require_approval: false,
    ticket_requests_disabled: false,
    ticket_require_approval: false,
    options: {
      kind: "Ssh",
      host: $host,
      port: 2222,
      username: "developer",
      allow_insecure_algos: false,
      auth: {kind: "PublicKey"}
    }
  }')

targets=$(api_get "/targets?search=$target_name")
target_id=$(printf '%s' "$targets" | exact_id name "$target_name") || target_id=
if [ -n "$target_id" ]; then
  api_write PUT "/targets/$target_id" "$target_body" >/dev/null
else
  target_id=$(api_write POST /targets "$target_body" | jq --exit-status --raw-output '.id')
fi

user_roles=$(api_get "/users/$admin_id/roles")
if ! printf '%s' "$user_roles" | jq --exit-status --arg id "$role_id" 'any(.id == $id)' >/dev/null; then
  api_write POST "/users/$admin_id/roles/$role_id" null >/dev/null
fi

target_roles=$(api_get "/targets/$target_id/roles")
if ! printf '%s' "$target_roles" | jq --exit-status --arg id "$role_id" 'any(.id == $id)' >/dev/null; then
  api_write POST "/targets/$target_id/roles/$role_id" >/dev/null
fi

if [ -n "$sso_username" ]; then
  sso_users=$(api_get "/users?search=$sso_username")
  sso_user_id=$(printf '%s' "$sso_users" | exact_id username "$sso_username") || sso_user_id=
  if [ -n "$sso_user_id" ]; then
    sso_user_body=$(printf '%s' "$sso_users" | jq --compact-output --exit-status \
      --arg username "$sso_username" \
      '.[] | select(.username == $username) | . as $user |
      {
        username,
        description: (.description // "Agent Workspace AW0 SSO user"),
        credential_policy: ((.credential_policy // {}) + {
          http: ["Sso"],
          ssh: ["WebUserApproval"]
        })
      } + ($user | {rate_limit_bytes_per_second, allowed_ip_ranges} |
        with_entries(select(.value != null)))')
    api_write PUT "/users/$sso_user_id" "$sso_user_body" >/dev/null
    sso_user_roles=$(api_get "/users/$sso_user_id/roles")
    if ! printf '%s' "$sso_user_roles" | jq --exit-status --arg id "$role_id" \
      'any(.id == $id)' >/dev/null; then
      api_write POST "/users/$sso_user_id/roles/$role_id" null >/dev/null
    fi
    echo "Warpgate SSO user $sso_username is bound to $target_name."
  else
    echo "NOTICE: log into Warpgate with Keycloak once, then rerun to bind $sso_username."
  fi
fi

api_get "/targets/$target_id" | jq --exit-status \
  --arg name "$target_name" \
  --arg host "$target_host" \
  '.name == $name and .options.host == $host and .options.port == 2222' >/dev/null

if ! kubectl get secret warpgate-secrets --namespace "$namespace" >/dev/null 2>&1; then
  kubectl create secret generic warpgate-aw0-api \
    --namespace "$namespace" \
    --from-literal=token="$token" \
    --dry-run=client \
    --output=yaml | kubectl apply -f - >/dev/null
fi

echo "Warpgate target, role, admin bindings and browser SSH approval are ready."
