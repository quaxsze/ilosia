#!/bin/sh
set -eu

namespace=ilosia
deployment=keycloak
recovery_job=keycloak-admin-recovery
recovery_secret=keycloak-admin-recovery
recovery_username=ilosia-recovery-admin
permanent_username=ilosia-admin
expected_context="k3d-${K3D_CLUSTER_NAME:-ilosia}"
new_password=${KEYCLOAK_ADMIN_PASSWORD:-}
manifest=$(mktemp)
patch_file=$(mktemp)
recovery_created=false
completed=false
original_replicas=
umask 077

cleanup() {
  if [ -n "$original_replicas" ]; then
    kubectl scale deployment "$deployment" --namespace "$namespace" \
      --replicas="$original_replicas" >/dev/null 2>&1 || true
  fi
  kubectl delete job "$recovery_job" --namespace "$namespace" \
    --ignore-not-found >/dev/null 2>&1 || true
  if [ "$completed" = true ] || [ "$recovery_created" = false ]; then
    kubectl delete secret "$recovery_secret" --namespace "$namespace" \
      --ignore-not-found >/dev/null 2>&1 || true
  else
    echo "Recovery did not finish; $namespace/$recovery_secret was retained." >&2
  fi
  rm -f "$manifest" "$patch_file"
}
trap cleanup EXIT INT TERM

context=$(kubectl config current-context)
if [ "$context" != "$expected_context" ]; then
  echo "Refusing admin recovery on $context; expected $expected_context." >&2
  exit 1
fi

if [ -z "$new_password" ]; then
  cat >&2 <<'EOF'
Choose a new admin password and pass it without writing it to shell history:
  read -s KEYCLOAK_ADMIN_PASSWORD
  export KEYCLOAK_ADMIN_PASSWORD
  ./scripts/recover_local_keycloak_admin.sh
EOF
  exit 2
fi

if [ "${#new_password}" -lt 16 ]; then
  echo "The new Keycloak admin password must contain at least 16 characters." >&2
  exit 2
fi

original_replicas=$(kubectl get deployment "$deployment" --namespace "$namespace" \
  --output=jsonpath='{.spec.replicas}')
image=$(kubectl get deployment "$deployment" --namespace "$namespace" \
  --output=jsonpath='{.spec.template.spec.containers[?(@.name=="keycloak")].image}')
[ -n "$image" ] || {
  echo "Could not determine the Keycloak image." >&2
  exit 1
}

recovery_user_count=$(kubectl exec --namespace "$namespace" deployment/keycloak-postgres -- \
  psql -U keycloak -d keycloak -Atc \
  "SELECT count(*) FROM user_entity u JOIN realm r ON r.id = u.realm_id WHERE r.name = 'master' AND u.username = '$recovery_username';")

if [ "$recovery_user_count" -eq 1 ]; then
  if ! kubectl get secret "$recovery_secret" --namespace "$namespace" >/dev/null 2>&1; then
    echo "Recovery user exists but its temporary Secret is missing; remove it manually first." >&2
    exit 1
  fi
  recovery_password=$(kubectl get secret "$recovery_secret" --namespace "$namespace" \
    --output='go-template={{index .data "password" | base64decode}}')
  recovery_created=true
  echo "Resuming the previous recovery attempt."
else
  [ "$recovery_user_count" -eq 0 ] || {
    echo "Expected at most one $recovery_username user, found $recovery_user_count." >&2
    exit 1
  }
  recovery_password=$(openssl rand -hex 32)
  kubectl create secret generic "$recovery_secret" \
    --namespace "$namespace" \
    --from-literal=password="$recovery_password" \
    --dry-run=client --output=yaml | kubectl apply -f - >/dev/null

  echo "Stopping Keycloak for exclusive admin recovery..."
  kubectl scale deployment "$deployment" --namespace "$namespace" --replicas=0 >/dev/null
  if kubectl get pod --namespace "$namespace" \
    --selector app.kubernetes.io/name=keycloak --output=name | grep -q .; then
    kubectl wait --namespace "$namespace" --for=delete pod \
      --selector app.kubernetes.io/name=keycloak --timeout=180s
  fi

  cat >"$manifest" <<EOF
apiVersion: batch/v1
kind: Job
metadata:
  name: $recovery_job
  namespace: $namespace
spec:
  backoffLimit: 0
  template:
    spec:
      restartPolicy: Never
      securityContext:
        runAsNonRoot: true
        runAsUser: 1000
        runAsGroup: 1000
        seccompProfile:
          type: RuntimeDefault
      containers:
        - name: recovery
          image: $image
          args:
            - bootstrap-admin
            - user
            - --username
            - $recovery_username
            - --password:env
            - RECOVERY_PASSWORD
            - --no-prompt
          env:
            - name: KC_DB
              value: postgres
            - name: KC_DB_URL
              value: jdbc:postgresql://keycloak-postgres:5432/keycloak
            - name: KC_DB_USERNAME
              value: keycloak
            - name: KC_DB_PASSWORD
              valueFrom:
                secretKeyRef:
                  name: ilosia-secrets
                  key: KEYCLOAK_POSTGRES_PASSWORD
            - name: RECOVERY_PASSWORD
              valueFrom:
                secretKeyRef:
                  name: $recovery_secret
                  key: password
          securityContext:
            allowPrivilegeEscalation: false
            capabilities:
              drop: [ALL]
          resources:
            requests:
              cpu: 100m
              memory: 256Mi
            limits:
              cpu: "1"
              memory: 1Gi
EOF

  kubectl delete job "$recovery_job" --namespace "$namespace" \
    --ignore-not-found >/dev/null
  kubectl apply --filename "$manifest" >/dev/null
  if ! kubectl wait --namespace "$namespace" --for=condition=Complete \
    "job/$recovery_job" --timeout=5m; then
    kubectl logs --namespace "$namespace" "job/$recovery_job" >&2 || true
    exit 1
  fi
  recovery_created=true

  echo "Restarting Keycloak with the temporary recovery administrator..."
  kubectl scale deployment "$deployment" --namespace "$namespace" \
    --replicas="$original_replicas" >/dev/null
  kubectl rollout status deployment "$deployment" --namespace "$namespace" --timeout=5m
fi

keycloak_pod=$(kubectl get pod --namespace "$namespace" \
  --selector app.kubernetes.io/name=keycloak \
  --field-selector=status.phase=Running \
  --output=jsonpath='{.items[0].metadata.name}')
kcadm() {
  kubectl exec --namespace "$namespace" "$keycloak_pod" -- \
    /opt/keycloak/bin/kcadm.sh "$@"
}

kcadm config credentials --server http://127.0.0.1:8080 --realm master \
  --user "$recovery_username" --password "$recovery_password" >/dev/null
master_users=$(kcadm get users --realm master --query "username=$permanent_username")
permanent_id=$(printf '%s' "$master_users" | jq --raw-output --arg username "$permanent_username" \
  '[.[] | select(.username == $username)] | if length == 1 then .[0].id else empty end')
if [ -z "$permanent_id" ]; then
  kcadm create users --realm master \
    -s "username=$permanent_username" -s enabled=true >/dev/null
  master_users=$(kcadm get users --realm master --query "username=$permanent_username")
  permanent_id=$(printf '%s' "$master_users" | jq --exit-status --raw-output \
    --arg username "$permanent_username" \
    '[.[] | select(.username == $username)] | if length == 1 then .[0].id else empty end')
fi

jq --null-input --arg password "$new_password" \
  '{type: "password", value: $password, temporary: false}' |
  kubectl exec --stdin --namespace "$namespace" "$keycloak_pod" -- \
    /opt/keycloak/bin/kcadm.sh update "users/$permanent_id/reset-password" \
      --realm master -n --file - >/dev/null
kcadm add-roles --realm master --uusername "$permanent_username" --rolename admin >/dev/null

kcadm config credentials --server http://127.0.0.1:8080 --realm master \
  --user "$permanent_username" --password "$new_password" >/dev/null
recovery_users=$(kcadm get users --realm master --query "username=$recovery_username")
recovery_id=$(printf '%s' "$recovery_users" | jq --exit-status --raw-output \
  --arg username "$recovery_username" \
  '[.[] | select(.username == $username)] | if length == 1 then .[0].id else empty end')
kcadm delete "users/$recovery_id" --realm master >/dev/null
recovery_created=false

encoded_username=$(printf '%s' "$permanent_username" | base64 | tr -d '\n')
encoded_password=$(printf '%s' "$new_password" | base64 | tr -d '\n')
jq --null-input --arg username "$encoded_username" --arg password "$encoded_password" \
  '{data: {
    KEYCLOAK_ADMIN_USERNAME: $username,
    KEYCLOAK_ADMIN_PASSWORD: $password
  }}' >"$patch_file"
kubectl patch secret ilosia-secrets --namespace "$namespace" \
  --type=merge --patch-file "$patch_file" >/dev/null
kubectl rollout restart deployment "$deployment" --namespace "$namespace" >/dev/null
kubectl rollout status deployment "$deployment" --namespace "$namespace" --timeout=5m

keycloak_pod=$(kubectl get pod --namespace "$namespace" \
  --selector app.kubernetes.io/name=keycloak \
  --field-selector=status.phase=Running \
  --output=jsonpath='{.items[0].metadata.name}')
kubectl exec --namespace "$namespace" "$keycloak_pod" -- \
  /opt/keycloak/bin/kcadm.sh get realms/master \
    --no-config --server http://127.0.0.1:8080 --realm master \
    --user "$permanent_username" --password "$new_password" >/dev/null

completed=true
echo "PASS: permanent Keycloak admin $permanent_username created, Secret synchronized, and recovery user removed."
