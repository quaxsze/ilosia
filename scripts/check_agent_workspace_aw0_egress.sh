#!/bin/sh
set -eu

namespace=${1:-aw0-workspace}
selector=${2:-app.kubernetes.io/name=aw0-workspace}

pod=$(kubectl get pods --namespace "$namespace" --selector "$selector" \
  --field-selector=status.phase=Running --output=name | sed -n '1s|pod/||p')
[ -n "$pod" ] || {
  echo "No running Agent Workspace Pod found in $namespace." >&2
  exit 1
}

run_curl() {
  kubectl exec --namespace "$namespace" "$pod" --container workspace -- \
    curl --insecure --silent --show-error --output /dev/null \
      --connect-timeout 3 --max-time 6 "$1"
}

expect_allowed() {
  if run_curl "$2"; then
    echo "PASS: $1 is reachable."
  else
    echo "FAIL: $1 should be reachable." >&2
    return 1
  fi
}

expect_denied() {
  if run_curl "$2" >/dev/null 2>&1; then
    echo "FAIL: $1 should be blocked." >&2
    return 1
  fi
  echo "PASS: $1 is unreachable."
}

failures=0
expect_allowed 'github.com:443' 'https://github.com/' || failures=$((failures + 1))
expect_allowed 'api.openai.com:443' 'https://api.openai.com/v1/models' || failures=$((failures + 1))
expect_denied 'public TCP 80' 'http://example.com/' || failures=$((failures + 1))
expect_denied 'kubernetes.default.svc:443' 'https://kubernetes.default.svc/' || failures=$((failures + 1))

node_ip=$(kubectl get nodes --output=jsonpath='{.items[0].status.addresses[?(@.type=="InternalIP")].address}')
if [ -n "$node_ip" ]; then
  expect_denied "node API $node_ip:6443" "https://$node_ip:6443/" || failures=$((failures + 1))
fi

expect_denied 'Scaleway metadata 169.254.42.42' 'http://169.254.42.42/' || failures=$((failures + 1))
expect_denied 'cloud metadata 169.254.169.254' 'http://169.254.169.254/' || failures=$((failures + 1))

if [ "$failures" -ne 0 ]; then
  echo "$failures egress check(s) failed." >&2
  exit 1
fi

echo 'PASS: Agent Workspace egress policy matches the AW0 expectations.'
