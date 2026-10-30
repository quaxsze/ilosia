#!/bin/sh
set -eu

cluster_name=${K3D_CLUSTER_NAME:-ilosia}
proxy_name=ilosia-aw1-https-proxy
listen_port=${WARPGATE_PUBLIC_PORT:-8443}
service_name=${NGINX_INGRESS_SERVICE:-nginx-ingress-controller}
external_ip=$(kubectl get service "$service_name" --namespace nginx-ingress \
  --output=jsonpath='{.status.loadBalancer.ingress[0].ip}')
[ -n "$external_ip" ] || {
  echo "NGINX Ingress has no LoadBalancer IP." >&2
  exit 1
}

if docker container inspect "$proxy_name" >/dev/null 2>&1; then
  if [ "$(docker inspect --format '{{.State.Running}}' "$proxy_name")" != true ]; then
    docker start "$proxy_name" >/dev/null
  fi
  docker port "$proxy_name" 8443/tcp
  exit
fi

docker run --detach \
  --name "$proxy_name" \
  --network "k3d-$cluster_name" \
  --publish "$listen_port:8443" \
  alpine/socat \
  -dd TCP-LISTEN:8443,fork,reuseaddr "TCP:$external_ip:443" >/dev/null

echo "Warpgate HTTPS proxy started at https://warpgate.localhost:$listen_port."
echo "Remove it with: docker rm --force $proxy_name"
