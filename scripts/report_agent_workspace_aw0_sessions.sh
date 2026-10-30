#!/bin/sh
set -eu

namespace=warpgate
secret=warpgate-aw0-api
api_url=https://127.0.0.1:18888/@warpgate/admin/api/sessions
username=${1:-admin}

token=$(kubectl get secret "$secret" --namespace "$namespace" \
  --output='go-template={{index .data "token" | base64decode}}')

port_forward_log=$(mktemp)
kubectl port-forward --namespace "$namespace" service/warpgate 18888:8888 \
  >"$port_forward_log" 2>&1 &
port_forward_pid=$!
trap 'kill "$port_forward_pid" 2>/dev/null || true; wait "$port_forward_pid" 2>/dev/null || true; rm -f "$port_forward_log"' EXIT INT TERM

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

curl --insecure --silent --show-error --fail --max-time 10 \
  --header "x-warpgate-token: $token" "$api_url" | jq --arg username "$username" '
    [.. | objects |
      select(.username? == $username and ((.protocol? // "") | ascii_upcase) == "SSH")]
    | sort_by(.started) | reverse
    | {
        ssh_session_count: length,
        recent_sessions: (.[0:20] | map({id, started, ended, username, protocol}))
      }
  '
