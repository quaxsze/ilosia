#!/bin/sh
set -eu

e2e_mode=false
namespace="${1:-user-1}"
other_namespace="${2:-}"
temporary_user_a=""
temporary_user_b=""
temporary_namespace_a=""
temporary_namespace_b=""
pod_a=""
key=""
local_file=""

if [ "$namespace" = "--e2e" ] || [ "$other_namespace" = "--with-temporary-user" ]; then
  e2e_mode=true
  namespace=""
  other_namespace=""
fi

cleanup() {
  if [ -n "$pod_a" ] && [ -n "$local_file" ]; then
    kubectl exec --namespace "$namespace" "$pod_a" -- rm -f "$local_file" \
      >/dev/null 2>&1 || true
  fi
  if [ -n "$pod_a" ] && [ -n "$key" ]; then
    kubectl exec --stdin --namespace "$namespace" "$pod_a" -- \
      env CHECK_KEY="$key" python - >/dev/null 2>&1 <<'PY' || true
import os
import boto3
from botocore.config import Config

s3 = boto3.client(
    "s3",
    endpoint_url=os.environ["S3_ENDPOINT"],
    aws_access_key_id=os.environ["S3_ACCESS_KEY"],
    aws_secret_access_key=os.environ["S3_SECRET_KEY"],
    region_name="garage",
    config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
)
s3.delete_object(Bucket=os.environ["S3_BUCKET"], Key=os.environ["CHECK_KEY"])
PY
  fi
  for temporary_user in "$temporary_user_b" "$temporary_user_a"; do
    if [ -n "$temporary_user" ]; then
      echo "Cleaning up temporary user $temporary_user..."
      kubectl exec --namespace ilosia deployment/ilosia-web -- \
        python manage.py storage_test_workload cleanup \
        --user-id "$temporary_user" || \
        echo "WARNING: application cleanup was incomplete for user $temporary_user." >&2
    fi
  done
  for temporary_namespace in "$temporary_namespace_b" "$temporary_namespace_a"; do
    if [ -n "$temporary_namespace" ]; then
      kubectl delete namespace "$temporary_namespace" --wait=false \
        >/dev/null 2>&1 || true
    fi
  done
  temporary_user_a=""
  temporary_user_b=""
}
trap cleanup EXIT INT TERM

if [ "$e2e_mode" = true ]; then
  echo "Creating temporary user A with two Jupyter services..."
  temporary_result=$(kubectl exec --namespace ilosia deployment/ilosia-web -- \
    python manage.py storage_test_workload create --services 2)
  set -- $temporary_result
  if [ "$#" -ne 3 ]; then
    echo "Unexpected temporary user response: $temporary_result" >&2
    exit 1
  fi
  temporary_namespace_a=$1
  temporary_user_a=$2
  if [ "$3" != "RUNNING" ]; then
    echo "Temporary user A launch failed with status $3." >&2
    exit 1
  fi

  echo "Creating temporary user B with one Jupyter service..."
  temporary_result=$(kubectl exec --namespace ilosia deployment/ilosia-web -- \
    python manage.py storage_test_workload create --services 1)
  set -- $temporary_result
  if [ "$#" -ne 3 ]; then
    echo "Unexpected temporary user response: $temporary_result" >&2
    exit 1
  fi
  temporary_namespace_b=$1
  temporary_user_b=$2
  if [ "$3" != "RUNNING" ]; then
    echo "Temporary user B launch failed with status $3." >&2
    exit 1
  fi
  namespace=$temporary_namespace_a
  other_namespace=$temporary_namespace_b
fi

pods=$(kubectl get pods \
  --namespace "$namespace" \
  --selector app.kubernetes.io/name=jupyter \
  --field-selector status.phase=Running \
  --output jsonpath='{range .items[*]}{.metadata.name}{"\n"}{end}')
set -- $pods

if [ "$#" -lt 2 ]; then
  echo "Launch two running Jupyter services in $namespace, then retry." >&2
  exit 1
fi

pod_a=$1
pod_b=$2
check_id=$(date +%s)-$$
key="ilosia-storage-check/$check_id.txt"
content="shared-from-$pod_a"
local_file="/home/jovyan/work/.ilosia-storage-check-$check_id"

for pod in "$pod_a" "$pod_b"; do
  kubectl wait --namespace "$namespace" --for=condition=Ready "pod/$pod" --timeout=60s >/dev/null
  if ! kubectl exec --namespace "$namespace" "$pod" -- python -c 'import boto3' >/dev/null 2>&1; then
    echo "Installing boto3 temporarily in $pod..."
    kubectl exec --namespace "$namespace" "$pod" -- \
      python -m pip install --quiet --user boto3
  fi
done

bucket_a=$(kubectl exec --namespace "$namespace" "$pod_a" -- python -c '
import os
required = ("S3_ENDPOINT", "S3_BUCKET", "S3_ACCESS_KEY", "S3_SECRET_KEY")
missing = [name for name in required if not os.getenv(name)]
if missing:
    raise SystemExit(f"Missing S3 variables: {missing}")
print(os.environ["S3_BUCKET"])
')
bucket_b=$(kubectl exec --namespace "$namespace" "$pod_b" -- python -c '
import os
required = ("S3_ENDPOINT", "S3_BUCKET", "S3_ACCESS_KEY", "S3_SECRET_KEY")
missing = [name for name in required if not os.getenv(name)]
if missing:
    raise SystemExit(f"Missing S3 variables: {missing}")
print(os.environ["S3_BUCKET"])
')

if [ "$bucket_a" != "$bucket_b" ] || [ "$bucket_a" != "$namespace" ]; then
  echo "Unexpected buckets: $pod_a=$bucket_a, $pod_b=$bucket_b" >&2
  exit 1
fi

for pod in "$pod_a" "$pod_b"; do
  if ! kubectl exec --namespace "$namespace" "$pod" -- python -c '
import os
import socket
from urllib.parse import urlsplit

endpoint = urlsplit(os.environ["S3_ENDPOINT"])
socket.getaddrinfo(endpoint.hostname, endpoint.port)
' >/dev/null 2>&1; then
    echo "S3_ENDPOINT cannot be resolved from $pod; deploy the latest Ilosia chart and recreate the service." >&2
    exit 1
  fi
done

pvc_a=$(kubectl get pod --namespace "$namespace" "$pod_a" \
  --output jsonpath='{.spec.volumes[?(@.name=="work")].persistentVolumeClaim.claimName}')
pvc_b=$(kubectl get pod --namespace "$namespace" "$pod_b" \
  --output jsonpath='{.spec.volumes[?(@.name=="work")].persistentVolumeClaim.claimName}')
if [ -z "$pvc_a" ] || [ -z "$pvc_b" ] || [ "$pvc_a" = "$pvc_b" ]; then
  echo "The two Jupyter services must use distinct PVCs." >&2
  exit 1
fi

kubectl exec --stdin --namespace "$namespace" "$pod_a" -- \
  env CHECK_KEY="$key" CHECK_CONTENT="$content" CHECK_LOCAL="$local_file" \
  python - <<'PY'
import os
from pathlib import Path

import boto3
from botocore.config import Config

Path(os.environ["CHECK_LOCAL"]).write_text(os.environ["CHECK_CONTENT"])
s3 = boto3.client(
    "s3",
    endpoint_url=os.environ["S3_ENDPOINT"],
    aws_access_key_id=os.environ["S3_ACCESS_KEY"],
    aws_secret_access_key=os.environ["S3_SECRET_KEY"],
    region_name="garage",
    config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
)
s3.put_object(
    Bucket=os.environ["S3_BUCKET"],
    Key=os.environ["CHECK_KEY"],
    Body=os.environ["CHECK_CONTENT"].encode(),
)
PY

kubectl exec --stdin --namespace "$namespace" "$pod_b" -- \
  env CHECK_KEY="$key" CHECK_CONTENT="$content" CHECK_LOCAL="$local_file" \
  python - <<'PY'
import os
from pathlib import Path

import boto3
from botocore.config import Config

if Path(os.environ["CHECK_LOCAL"]).exists():
    raise SystemExit("PVC isolation failed: Jupyter B can see Jupyter A's local file")
s3 = boto3.client(
    "s3",
    endpoint_url=os.environ["S3_ENDPOINT"],
    aws_access_key_id=os.environ["S3_ACCESS_KEY"],
    aws_secret_access_key=os.environ["S3_SECRET_KEY"],
    region_name="garage",
    config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
)
body = s3.get_object(
    Bucket=os.environ["S3_BUCKET"], Key=os.environ["CHECK_KEY"]
)["Body"].read().decode()
if body != os.environ["CHECK_CONTENT"]:
    raise SystemExit("S3 content mismatch")
PY

echo "PASS: $pod_a and $pod_b use distinct PVCs ($pvc_a, $pvc_b)."
echo "PASS: both services share the S3 bucket $bucket_a."

assert_bucket_denied() {
  check_namespace=$1
  check_pod=$2
  target_bucket=$3
  kubectl exec --stdin --namespace "$check_namespace" "$check_pod" -- \
    env TARGET_BUCKET="$target_bucket" python - <<'PY'
import os

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

s3 = boto3.client(
    "s3",
    endpoint_url=os.environ["S3_ENDPOINT"],
    aws_access_key_id=os.environ["S3_ACCESS_KEY"],
    aws_secret_access_key=os.environ["S3_SECRET_KEY"],
    region_name="garage",
    config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
)
try:
    s3.head_bucket(Bucket=os.environ["TARGET_BUCKET"])
except ClientError as error:
    code = str(error.response.get("Error", {}).get("Code"))
    if code in {"403", "404", "AccessDenied", "NoSuchBucket"}:
        raise SystemExit(0)
    raise
raise SystemExit("S3 isolation failed: this user can access another user's bucket")
PY
}

if [ -n "$other_namespace" ]; then
  other_pods=$(kubectl get pods \
    --namespace "$other_namespace" \
    --selector app.kubernetes.io/name=jupyter \
    --field-selector status.phase=Running \
    --output jsonpath='{range .items[*]}{.metadata.name}{" "}{end}')
  other_pod=${other_pods%% *}
  if [ -z "$other_pod" ]; then
    echo "Launch one running Jupyter service in $other_namespace, then retry." >&2
    exit 1
  fi
  kubectl wait --namespace "$other_namespace" --for=condition=Ready \
    "pod/$other_pod" --timeout=60s >/dev/null
  if ! kubectl exec --namespace "$other_namespace" "$other_pod" -- \
    python -c 'import boto3' >/dev/null 2>&1; then
    echo "Installing boto3 temporarily in $other_pod..."
    kubectl exec --namespace "$other_namespace" "$other_pod" -- \
      python -m pip install --quiet --user boto3
  fi
  other_bucket=$(kubectl exec --namespace "$other_namespace" "$other_pod" -- \
    python -c 'import os; print(os.environ["S3_BUCKET"])')
  if [ "$other_bucket" != "$other_namespace" ]; then
    echo "Unexpected bucket: $other_pod=$other_bucket" >&2
    exit 1
  fi
  assert_bucket_denied "$other_namespace" "$other_pod" "$bucket_a"
  echo "PASS: $other_namespace cannot access the S3 bucket $bucket_a."
  assert_bucket_denied "$namespace" "$pod_a" "$other_bucket"
  echo "PASS: $namespace cannot access the S3 bucket $other_bucket."
fi
