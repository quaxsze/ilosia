#!/bin/sh
set -eu

repository_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$repository_root"

cluster=ilosia-aw0-benchmark
context=k3d-$cluster
registry=ilosia-aw0-benchmark-registry.localhost
registry_port=${AW0_BENCHMARK_REGISTRY_PORT:-5112}
namespace=aw0-benchmark
source_image=ilosia-agent-workspace-aw0:0.1.0
tag=run-$(date +%s)
host_image=localhost:$registry_port/ilosia-agent-workspace-aw0:$tag
cluster_image=$registry:$registry_port/ilosia-agent-workspace-aw0:$tag
small_repository=${AW0_BENCHMARK_SMALL_REPOSITORY:-https://github.com/quaxsze/ilosia.git}
large_repository=${AW0_BENCHMARK_LARGE_REPOSITORY:-https://github.com/kubernetes/kubernetes.git}
invalid_repository=https://github.com/quaxsze/ilosia-aw0-repository-does-not-exist.git
health_url=${AW0_BENCHMARK_HEALTH_URL:-http://ilosia.localhost:8080/healthz/}
report=${AW0_BENCHMARK_REPORT:-spikes/agent-workspace/AW0_BENCHMARK_RESULTS.md}
template=spikes/agent-workspace/benchmark-deployment.yaml
temporary_directory=$(mktemp -d)
cluster_created=0
tag_created=0
failures=0
worst_duration=0
health_monitor_pid=0

cleanup() {
  status=$?
  set +e
  if [ "$health_monitor_pid" != 0 ]; then
    : >"$temporary_directory/health-stop"
    kill "$health_monitor_pid" 2>/dev/null || true
    wait "$health_monitor_pid" 2>/dev/null || true
  fi
  if [ "${AW0_BENCHMARK_KEEP:-0}" = 1 ]; then
    echo "Keeping benchmark cluster $cluster because AW0_BENCHMARK_KEEP=1."
  elif [ "$cluster_created" = 1 ]; then
    k3d cluster delete "$cluster" >/dev/null 2>&1
    k3d registry delete "$registry" >/dev/null 2>&1
  fi
  if [ "$tag_created" = 1 ]; then
    docker image rm "$host_image" >/dev/null 2>&1
  fi
  rm -rf "$temporary_directory"
  exit "$status"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

for command in curl docker jq k3d kubectl sed; do
  command -v "$command" >/dev/null 2>&1 || {
    echo "Required command not found: $command" >&2
    exit 1
  }
done

case "$registry_port" in
  ''|*[!0-9]*) echo "AW0_BENCHMARK_REGISTRY_PORT must be a port number." >&2; exit 1 ;;
esac
if [ "$registry_port" -lt 1 ] || [ "$registry_port" -gt 65535 ]; then
  echo "AW0_BENCHMARK_REGISTRY_PORT must be between 1 and 65535." >&2
  exit 1
fi
case "$small_repository" in
  https://github.com/*/*.git) ;;
  *) echo "Small repository must be an HTTPS GitHub .git URL." >&2; exit 1 ;;
esac
case "$large_repository" in
  https://github.com/*/*.git) ;;
  *) echo "Large repository must be an HTTPS GitHub .git URL." >&2; exit 1 ;;
esac

if k3d cluster list --output=json | jq --exit-status --arg name "$cluster" \
  'any(.[]; .name == $name)' >/dev/null; then
  echo "Refusing to replace existing k3d cluster: $cluster" >&2
  exit 1
fi
if docker container inspect "$registry" >/dev/null 2>&1; then
  echo "Refusing to replace existing registry container: $registry" >&2
  exit 1
fi

if ! docker image inspect "$source_image" >/dev/null 2>&1; then
  docker build --tag "$source_image" spikes/agent-workspace/image
fi

echo "Creating isolated four-node benchmark cluster..."
cluster_created=1
k3d cluster create "$cluster" \
  --servers 1 \
  --agents 3 \
  --image rancher/k3s:v1.35.5-k3s1 \
  --registry-create "$registry:127.0.0.1:$registry_port" \
  --enforce-registry-port-match \
  --kubeconfig-update-default \
  --kubeconfig-switch-context=false \
  --wait \
  --timeout 180s

docker tag "$source_image" "$host_image"
tag_created=1
docker push "$host_image"

kubectl --context "$context" wait nodes --all --for=condition=Ready --timeout=180s
kubectl --context "$context" create namespace "$namespace"
kubectl --context "$context" label namespace "$namespace" \
  pod-security.kubernetes.io/enforce=restricted \
  pod-security.kubernetes.io/enforce-version=latest
kubectl --context "$context" create secret generic benchmark-authorized-keys \
  --namespace "$namespace" \
  --from-literal=authorizedKeys='ssh-ed25519 benchmark-only'

server_node=k3d-$cluster-server-0
large_node=k3d-$cluster-agent-0
concurrent_node_a=k3d-$cluster-agent-1
concurrent_node_b=k3d-$cluster-agent-2

for node in "$server_node" "$large_node" "$concurrent_node_a" "$concurrent_node_b"; do
  kubectl --context "$context" get node "$node" >/dev/null
done

render_case() {
  name=$1
  node=$2
  repository=$3
  destination=$temporary_directory/$name.yaml
  sed \
    -e "s|__NAME__|$name|g" \
    -e "s|__NAMESPACE__|$namespace|g" \
    -e "s|__NODE__|$node|g" \
    -e "s|__IMAGE__|$cluster_image|g" \
    -e "s|__REPOSITORY__|$repository|g" \
    "$template" >"$destination"
  if grep '__[A-Z_]*__' "$destination" >/dev/null; then
    echo "Unresolved placeholder in $destination" >&2
    exit 1
  fi
  printf '%s\n' "$destination"
}

image_is_cached() {
  node=$1
  docker exec "$node" crictl images --output=json | jq --exit-status \
    --arg image "$cluster_image" \
    'any(.images[]?.repoTags[]?; . == $image)' >/dev/null
}

delete_case() {
  name=$1
  kubectl --context "$context" delete deployment "$name" \
    --namespace "$namespace" --ignore-not-found --wait=true >/dev/null
  kubectl --context "$context" delete pvc "$name-data" \
    --namespace "$namespace" --ignore-not-found --wait=true >/dev/null
}

append_result() {
  label=$1
  duration=$2
  health=$3
  result=$4
  printf '| %s | %ss | %s | %s |\n' "$label" "$duration" "$health" "$result" >>"$report"
  if [ "$duration" -gt "$worst_duration" ]; then
    worst_duration=$duration
  fi
}

diagnose_case() {
  name=$1
  kubectl --context "$context" get pods --namespace "$namespace" \
    --selector "app.kubernetes.io/name=$name" --output=wide >&2 || true
  pod=$(kubectl --context "$context" get pods --namespace "$namespace" \
    --selector "app.kubernetes.io/name=$name" --output=name | sed -n '1p')
  if [ -n "$pod" ]; then
    kubectl --context "$context" describe --namespace "$namespace" "$pod" >&2 || true
    kubectl --context "$context" logs --namespace "$namespace" "$pod" \
      --container clone --tail=40 >&2 || true
  fi
}

run_case() {
  label=$1
  name=$2
  node=$3
  repository=$4
  expected_cache=$5
  case_failed=0

  echo "Benchmarking: $label"

  if [ "$expected_cache" = cold ] && image_is_cached "$node"; then
    echo "FAIL: $cluster_image is already cached on $node." >&2
    exit 1
  fi
  if [ "$expected_cache" = cached ] && ! image_is_cached "$node"; then
    echo "FAIL: $cluster_image is not cached on $node." >&2
    exit 1
  fi

  manifest=$(render_case "$name" "$node" "$repository")
  start=$(date +%s)
  kubectl --context "$context" apply --filename "$manifest" >/dev/null
  if kubectl --context "$context" rollout status "deployment/$name" \
    --namespace "$namespace" --timeout=360s >/dev/null; then
    duration=$(($(date +%s) - start))
    if [ "$duration" -le 300 ]; then
      result=passed
    else
      result='failed: exceeded 300s Helm budget'
      failures=$((failures + 1))
    fi
  else
    duration=$(($(date +%s) - start))
    result='failed: workload not ready'
    failures=$((failures + 1))
    case_failed=1
    diagnose_case "$name"
  fi
  append_result "$label" "$duration" 'n/a' "$result"
  delete_case "$name"
  if [ "$case_failed" = 1 ]; then
    return 1
  fi
}

run_invalid_case() {
  name=bench-invalid
  manifest=$(render_case "$name" "$server_node" "$invalid_repository")
  echo 'Benchmarking: invalid repository'
  start=$(date +%s)
  kubectl --context "$context" apply --filename "$manifest" >/dev/null
  detected=0
  while [ $(($(date +%s) - start)) -lt 120 ]; do
    if kubectl --context "$context" get pods --namespace "$namespace" \
      --selector "app.kubernetes.io/name=$name" --output=json | jq --exit-status '
        any(.items[].status.initContainerStatuses[]?;
          ((.state.terminated.exitCode? // 0) != 0) or
          ((.lastState.terminated.exitCode? // 0) != 0))
      ' >/dev/null; then
      detected=1
      break
    fi
    sleep 1
  done
  duration=$(($(date +%s) - start))
  if [ "$detected" = 1 ]; then
    result='passed: clone failure detected'
  else
    result='failed: clone failure not detected within 120s'
    failures=$((failures + 1))
  fi
  append_result 'invalid repository' "$duration" 'n/a' "$result"
  delete_case "$name"
}

start_health_monitor() {
  health_monitor_pid=0
  rm -f "$temporary_directory/health-failed"
  if ! curl --silent --show-error --fail --max-time 3 "$health_url" >/dev/null 2>&1; then
    return
  fi
  rm -f "$temporary_directory/health-stop"
  (
    while [ ! -f "$temporary_directory/health-stop" ]; do
      curl --silent --show-error --fail --max-time 3 "$health_url" >/dev/null 2>&1 || \
        : >"$temporary_directory/health-failed"
      sleep 1
    done
  ) &
  health_monitor_pid=$!
}

run_concurrent_cold_case() {
  name_a=bench-concurrent-a
  name_b=bench-concurrent-b
  if image_is_cached "$concurrent_node_a" || image_is_cached "$concurrent_node_b"; then
    echo 'FAIL: concurrent benchmark nodes are not cold.' >&2
    exit 1
  fi
  manifest_a=$(render_case "$name_a" "$concurrent_node_a" "$small_repository")
  manifest_b=$(render_case "$name_b" "$concurrent_node_b" "$small_repository")
  echo 'Benchmarking: two simultaneous cold launches'
  start_health_monitor
  start=$(date +%s)
  kubectl --context "$context" apply --filename "$manifest_a" >/dev/null
  kubectl --context "$context" apply --filename "$manifest_b" >/dev/null
  kubectl --context "$context" rollout status "deployment/$name_a" \
    --namespace "$namespace" --timeout=360s >"$temporary_directory/concurrent-a.log" 2>&1 &
  pid_a=$!
  kubectl --context "$context" rollout status "deployment/$name_b" \
    --namespace "$namespace" --timeout=360s >"$temporary_directory/concurrent-b.log" 2>&1 &
  pid_b=$!
  status_a=0
  status_b=0
  wait "$pid_a" || status_a=$?
  wait "$pid_b" || status_b=$?
  duration=$(($(date +%s) - start))
  : >"$temporary_directory/health-stop"
  if [ "$health_monitor_pid" != 0 ]; then
    wait "$health_monitor_pid"
    health_monitor_pid=0
    if [ -f "$temporary_directory/health-failed" ]; then
      health=failed
      failures=$((failures + 1))
    else
      health=passed
    fi
  else
    health='not available before test'
  fi
  if [ "$status_a" = 0 ] && [ "$status_b" = 0 ] && [ "$duration" -le 300 ]; then
    result=passed
  else
    result='failed: one or both workloads missed the 300s budget'
    failures=$((failures + 1))
    diagnose_case "$name_a"
    diagnose_case "$name_b"
  fi
  append_result 'two simultaneous cold launches' "$duration" "$health" "$result"
  delete_case "$name_a"
  delete_case "$name_b"
}

mkdir -p "$(dirname -- "$report")"
cat >"$report" <<EOF
# AW0 Agent Workspace benchmark

- Date: $(date -u +%Y-%m-%dT%H:%M:%SZ)
- Image: \`$source_image\`, distributed through an isolated local registry
- Small repository: \`$small_repository\`
- Large repository: \`$large_repository\`
- Limit: 300 seconds per launch

| Scenario | Duration | Ilosia /healthz | Result |
|---|---:|---|---|
EOF

run_case 'cold image + small repository' bench-cold-small "$server_node" "$small_repository" cold
run_case 'cached image + small repository' bench-cached-small "$server_node" "$small_repository" cached
run_case 'cold image + large repository' bench-cold-large "$large_node" "$large_repository" cold
run_case 'cached image + large repository' bench-cached-large "$large_node" "$large_repository" cached
run_invalid_case
run_concurrent_cold_case

cat >>"$report" <<EOF

The cold scenarios are first pulls from a local registry on distinct k3d nodes.
They measure unpacking and startup accurately but not WAN latency to GHCR.

The concurrent health check observes the existing local Ilosia deployment. It
measures shared Docker-host contention, not Django worker blocking; that must be
retested after the launch endpoint exists.

Worst observed launch: ${worst_duration}s.
EOF

cat "$report"
if [ "$failures" -ne 0 ]; then
  echo "$failures benchmark check(s) failed. Report: $report" >&2
  exit 1
fi
echo "PASS: benchmark completed. Report: $report"
