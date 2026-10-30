#!/bin/sh
set -eu

namespace=warpgate
output_dir=${WARPGATE_BACKUP_DIR:-backups/warpgate}
timestamp=$(date -u +%Y%m%dT%H%M%SZ)
archive=${1:-$output_dir/warpgate-$timestamp.tar.gz}
helper=warpgate-backup-$(date -u +%Y%m%d-%H%M%S)-$$
tmp_dir=$(mktemp -d)
trap 'kubectl delete pod "$helper" --namespace "$namespace" --ignore-not-found >/dev/null 2>&1 || true; rm -rf "$tmp_dir"' EXIT INT TERM
umask 077

for secret in warpgate-secrets warpgate-tls warpgate-tls-ca; do
  kubectl get secret "$secret" --namespace "$namespace" >/dev/null
done

pod=$(kubectl get pod --namespace "$namespace" \
  --selector app.kubernetes.io/instance=warpgate \
  --field-selector=status.phase=Running \
  --output=jsonpath='{.items[0].metadata.name}')
[ -n "$pod" ] || {
  echo "No running Warpgate Pod found." >&2
  exit 1
}
node=$(kubectl get pod "$pod" --namespace "$namespace" \
  --output=jsonpath='{.spec.nodeName}')
image=$(kubectl get deployment warpgate --namespace "$namespace" \
  --output=jsonpath='{.spec.template.spec.containers[0].image}')
version=$(kubectl exec --namespace "$namespace" "$pod" -- warpgate version)

cat <<EOF | kubectl apply -f - >/dev/null
apiVersion: v1
kind: Pod
metadata:
  name: $helper
  namespace: $namespace
spec:
  restartPolicy: Never
  nodeName: $node
  securityContext:
    runAsUser: 1000
    runAsGroup: 1000
    fsGroup: 1000
  containers:
    - name: backup
      image: python:3.12.12-alpine3.22
      command: [sleep, "3600"]
      volumeMounts:
        - name: data
          mountPath: /data
  volumes:
    - name: data
      persistentVolumeClaim:
        claimName: warpgate-data
EOF
kubectl wait --namespace "$namespace" --for=condition=Ready \
  "pod/$helper" --timeout=180s >/dev/null

kubectl exec --stdin --namespace "$namespace" "$helper" -- python - <<'PY'
import sqlite3

source = sqlite3.connect("file:/data/db/db.sqlite3?mode=ro", uri=True)
target = sqlite3.connect("/tmp/db.sqlite3")
with target:
    source.backup(target)
target.close()
source.close()
PY

kubectl exec --namespace "$namespace" "$helper" -- \
  tar -C /data --exclude=./db -czf - . >"$tmp_dir/data.tar.gz"
kubectl exec --namespace "$namespace" "$helper" -- \
  cat /tmp/db.sqlite3 >"$tmp_dir/db.sqlite3"
kubectl get secret warpgate-secrets warpgate-tls warpgate-tls-ca \
  --namespace "$namespace" --output=json >"$tmp_dir/secrets.json"
jq --null-input --arg image "$image" --arg version "$version" --arg created_at "$timestamp" \
  '{image: $image, version: $version, created_at: $created_at, database: "db.sqlite3"}' \
  >"$tmp_dir/metadata.json"

mkdir -p "$(dirname "$archive")"
tar -C "$tmp_dir" -czf "$archive" data.tar.gz db.sqlite3 secrets.json metadata.json
chmod 0600 "$archive"
echo "Warpgate backup created: $archive"
echo "It contains credentials and the encryption key; store it as a secret."
