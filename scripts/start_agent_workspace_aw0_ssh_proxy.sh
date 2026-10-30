#!/bin/sh
set -eu

cluster_name=${K3D_CLUSTER_NAME:-ilosia}
proxy_name="ilosia-aw0-ssh-proxy"
target="k3d-$cluster_name-server-0:2222"
http_proxy_name="ilosia-aw0-http-proxy"
http_target="k3d-$cluster_name-server-0:8888"

start_proxy() {
  name=$1
  port=$2
  destination=$3

  if docker container inspect "$name" >/dev/null 2>&1; then
    if [ "$(docker inspect --format '{{.State.Running}}' "$name")" != true ]; then
      docker start "$name" >/dev/null
    fi
    echo "$name already exists."
    docker port "$name" "$port/tcp"
    return
  fi

  docker run --detach \
    --name "$name" \
    --network "k3d-$cluster_name" \
    --publish "$port:$port" \
    alpine/socat \
    -dd "TCP-LISTEN:$port,fork,reuseaddr" "TCP:$destination" >/dev/null
  echo "Temporary proxy $name started on localhost:$port."
}

start_proxy "$proxy_name" 2222 "$target"
start_proxy "$http_proxy_name" 8888 "$http_target"
echo "Remove them with: docker rm --force $proxy_name $http_proxy_name"
