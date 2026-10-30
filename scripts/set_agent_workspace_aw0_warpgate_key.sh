#!/bin/sh
set -eu

if [ "$#" -gt 1 ]; then
  echo "Usage: $0 [warpgate-public-key-file]" >&2
  exit 1
fi

local_key_file=${AW0_AUTHORIZED_KEYS_FILE:-$HOME/.ssh/id_ed25519.pub}
warpgate_key_file=${1:-}
temporary_warpgate_key=

if [ -z "$warpgate_key_file" ]; then
  temporary_warpgate_key=$(mktemp)
  warpgate_key_file=$temporary_warpgate_key
  kubectl exec --namespace warpgate deployment/warpgate -- \
    warpgate client-keys 2>/dev/null | awk '/^ssh-ed25519 / {print; exit}' >"$warpgate_key_file"
fi

combined_keys=$(mktemp)
existing_keys=$(mktemp)
trap 'rm -f "$combined_keys" "$existing_keys" ${temporary_warpgate_key:+"$temporary_warpgate_key"}' EXIT INT TERM

for key_file in "$local_key_file" "$warpgate_key_file"; do
  if [ ! -s "$key_file" ]; then
    echo "Public key not found: $key_file" >&2
    exit 1
  fi
  if ! grep -Eq '^ssh-(ed25519|rsa) ' "$key_file"; then
    echo "Invalid OpenSSH public key: $key_file" >&2
    exit 1
  fi
done

awk 'NF && !seen[$0]++' "$local_key_file" "$warpgate_key_file" >"$combined_keys"

if kubectl get secret aw0-authorized-keys \
  --namespace aw0-workspace \
  --output='go-template={{index .data "authorizedKeys" | base64decode}}' >"$existing_keys" 2>/dev/null && \
  cmp -s "$combined_keys" "$existing_keys"; then
  echo "Warpgate and local fallback keys are already authorized."
  exit 0
fi

kubectl create secret generic aw0-authorized-keys \
  --namespace aw0-workspace \
  --from-file=authorizedKeys="$combined_keys" \
  --dry-run=client \
  --output=yaml | kubectl apply -f -
kubectl rollout restart deployment/aw0-workspace --namespace aw0-workspace
kubectl rollout status deployment/aw0-workspace \
  --namespace aw0-workspace \
  --timeout=5m

echo "Warpgate and local fallback keys are authorized."
