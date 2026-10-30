#!/bin/sh
set -eu

rendered=$(mktemp)
trap 'rm -f "$rendered"' EXIT INT TERM
chart=charts/agent-workspace
repository_url=https://github.com/quaxsze/ilosia.git
public_key='ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAITestOnlyKey agent-workspace-test'

render() {
  helm template test-agent "$chart" \
    --namespace user-42 \
    --set-string "repository.url=$repository_url" \
    --set-string "warpgate.publicKeys[0]=$public_key"
}

helm lint "$chart" \
  --set-string "repository.url=$repository_url" \
  --set-string "warpgate.publicKeys[0]=$public_key" >/dev/null
render >"$rendered"

assert_contains() {
  grep -Fq -- "$1" "$rendered" || {
    echo "Missing from rendered Agent Workspace chart: $1" >&2
    exit 1
  }
}

assert_contains 'automountServiceAccountToken: false'
assert_contains 'runAsNonRoot: true'
assert_contains 'runAsUser: 1000'
assert_contains 'readOnlyRootFilesystem: true'
assert_contains 'allowPrivilegeEscalation: false'
assert_contains 'seccompProfile:'
assert_contains 'ephemeral-storage: 2Gi'
assert_contains 'helm.sh/resource-policy: keep'
assert_contains 'claimName: test-agent-data'
assert_contains 'medium: Memory'
assert_contains 'tcpSocket:'
assert_contains 'port: 2222'
assert_contains 'port: 443'
assert_contains '- 169.254.0.0/16'
assert_contains 'kubernetes.io/metadata.name: warpgate'
assert_contains 'k8s-app: kube-dns'
assert_contains "value: \"$repository_url\""

if grep -Eq '^kind: Secret$' "$rendered"; then
  echo "Agent Workspace chart must not create a per-workspace Secret." >&2
  exit 1
fi
if helm template invalid "$chart" \
  --set-string "warpgate.publicKeys[0]=$public_key" >/dev/null 2>&1; then
  echo "Agent Workspace chart accepted an empty repository URL." >&2
  exit 1
fi
if helm template invalid "$chart" \
  --set-string "repository.url=$repository_url" >/dev/null 2>&1; then
  echo "Agent Workspace chart accepted an empty Warpgate public key list." >&2
  exit 1
fi

echo "PASS: Agent Workspace chart security and persistence invariants are rendered."
