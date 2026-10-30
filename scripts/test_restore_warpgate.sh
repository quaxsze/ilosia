#!/bin/sh
set -eu

if [ "$#" -ne 1 ]; then
  echo "Usage: $0 <warpgate-backup.tar.gz>" >&2
  exit 2
fi

archive=$1
namespace=${WARPGATE_RESTORE_NAMESPACE:-warpgate-restore-test}
keep=${KEEP_WARPGATE_RESTORE_TEST:-0}
tmp_dir=$(mktemp -d)
cleanup() {
  rm -rf "$tmp_dir"
  if [ "$keep" != 1 ]; then
    kubectl delete namespace "$namespace" --ignore-not-found >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT INT TERM

unexpected=$(tar -tzf "$archive" | grep -Ev '^(data.tar.gz|db.sqlite3|secrets.json|metadata.json)$' || true)
[ -z "$unexpected" ] || {
  echo "Backup contains unexpected files." >&2
  exit 1
}
tar -C "$tmp_dir" -xzf "$archive"
for file in data.tar.gz db.sqlite3 secrets.json metadata.json; do
  test -s "$tmp_dir/$file" || {
    echo "Backup is missing $file." >&2
    exit 1
  }
done
if tar -tzf "$tmp_dir/data.tar.gz" | grep -Eq '(^/|(^|/)\.\.(/|$))'; then
  echo "Backup data contains an unsafe path." >&2
  exit 1
fi

image=$(jq --exit-status --raw-output '.image' "$tmp_dir/metadata.json")
case "$image" in
  ghcr.io/warp-tech/warpgate:*) ;;
  *) echo "Unexpected Warpgate image in backup: $image" >&2; exit 1 ;;
esac
python3 - "$tmp_dir/db.sqlite3" <<'PY'
import sqlite3
import sys

connection = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
result = connection.execute("PRAGMA integrity_check").fetchone()[0]
connection.close()
if result != "ok":
    raise SystemExit(f"Backup database integrity check failed: {result}")
PY

kubectl create namespace "$namespace" --dry-run=client --output=yaml | \
  kubectl apply -f - >/dev/null
jq --arg namespace "$namespace" \
  '{apiVersion: "v1", kind: "List", items: [.items[] | del(.metadata.creationTimestamp, .metadata.resourceVersion, .metadata.uid, .metadata.managedFields) | .metadata.namespace = $namespace]}' \
  "$tmp_dir/secrets.json" | kubectl apply -f - >/dev/null

cat <<EOF | kubectl apply -f - >/dev/null
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: warpgate-restore-data
  namespace: $namespace
spec:
  accessModes: [ReadWriteOnce]
  resources:
    requests:
      storage: 1Gi
---
apiVersion: v1
kind: Pod
metadata:
  name: warpgate-restore-loader
  namespace: $namespace
spec:
  restartPolicy: Never
  securityContext:
    runAsUser: 1000
    runAsGroup: 1000
    fsGroup: 1000
  containers:
    - name: loader
      image: python:3.12.12-alpine3.22
      command: [sleep, "3600"]
      volumeMounts:
        - name: data
          mountPath: /data
  volumes:
    - name: data
      persistentVolumeClaim:
        claimName: warpgate-restore-data
EOF
kubectl wait --namespace "$namespace" --for=condition=Ready \
  pod/warpgate-restore-loader --timeout=180s >/dev/null
kubectl exec --stdin --namespace "$namespace" warpgate-restore-loader -- \
  tar -C /data -xzf - <"$tmp_dir/data.tar.gz"
kubectl cp "$tmp_dir/db.sqlite3" \
  "$namespace/warpgate-restore-loader:/tmp/db.sqlite3"
kubectl exec --namespace "$namespace" warpgate-restore-loader -- \
  sh -c 'mkdir -p /data/db; rm -f /data/db/db.sqlite3 /data/db/db.sqlite3-wal /data/db/db.sqlite3-shm; cp /tmp/db.sqlite3 /data/db/db.sqlite3; chmod 0600 /data/db/db.sqlite3; sync'
kubectl exec --stdin --namespace "$namespace" warpgate-restore-loader -- python - <<'PY'
import sqlite3

connection = sqlite3.connect("file:/data/db/db.sqlite3?mode=ro", uri=True)
result = connection.execute("PRAGMA integrity_check").fetchone()[0]
connection.close()
if result != "ok":
    raise SystemExit(f"Restored database integrity check failed: {result}")
print("SQLite restore integrity: ok")
PY
kubectl delete pod warpgate-restore-loader --namespace "$namespace" \
  --wait --timeout=120s >/dev/null

cat <<EOF | kubectl apply -f - >/dev/null
apiVersion: apps/v1
kind: Deployment
metadata:
  name: warpgate-restore
  namespace: $namespace
spec:
  replicas: 1
  strategy:
    type: Recreate
  selector:
    matchLabels:
      app.kubernetes.io/name: warpgate-restore
  template:
    metadata:
      labels:
        app.kubernetes.io/name: warpgate-restore
    spec:
      securityContext:
        runAsNonRoot: true
        runAsUser: 1000
        runAsGroup: 1000
        fsGroup: 1000
      containers:
        - name: warpgate
          image: $image
          command: [warpgate, -c, /data/warpgate.yaml, run]
          env:
            - name: WARPGATE_ENCRYPTION_KEY
              valueFrom:
                secretKeyRef:
                  name: warpgate-secrets
                  key: encryptionKey
          readinessProbe:
            exec:
              command: [warpgate, --config=/data/warpgate.yaml, healthcheck]
            timeoutSeconds: 10
          volumeMounts:
            - name: tls
              mountPath: /data/tls.certificate.pem
              subPath: tls.crt
              readOnly: true
            - name: tls
              mountPath: /data/tls.key.pem
              subPath: tls.key
              readOnly: true
            - name: data
              mountPath: /data
      volumes:
        - name: tls
          secret:
            secretName: warpgate-tls
        - name: data
          persistentVolumeClaim:
            claimName: warpgate-restore-data
EOF

if ! kubectl rollout status deployment/warpgate-restore \
  --namespace "$namespace" --timeout=5m; then
  kubectl get pods --namespace "$namespace" -o wide >&2
  kubectl logs deployment/warpgate-restore --namespace "$namespace" >&2 || true
  exit 1
fi
kubectl exec --namespace "$namespace" deployment/warpgate-restore -- \
  warpgate version
echo "PASS: Warpgate backup restored and started successfully in $namespace."
if [ "$keep" = 1 ]; then
  echo "Restore namespace retained because KEEP_WARPGATE_RESTORE_TEST=1."
fi
