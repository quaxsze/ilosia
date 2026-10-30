#!/bin/sh
set -eu

image=${1:?Usage: test_agent_workspace_image.sh IMAGE}

docker run --rm --entrypoint sh "$image" -c '
  set -eu
  test "$(id -u)" = 1000
  herdr --version
  codex --version
  uv --version
  mise --version
'

docker run --rm --workdir /tmp --tmpfs /workspace:rw,mode=1777 \
  --entrypoint sh "$image" -c '
  set -eu
  mkdir -p /workspace/repository
  touch /workspace/repository/keep-me
  if REPOSITORY_URL=file:///tmp/source.git /usr/local/bin/clone-repository; then
    echo "Clone replaced unexpected repository data." >&2
    exit 1
  fi
  test -f /workspace/repository/keep-me

  rm /workspace/repository/keep-me
  rmdir /workspace/repository
  git init --bare --quiet /tmp/source.git
  REPOSITORY_URL=file:///tmp/source.git /usr/local/bin/clone-repository
  test -e /workspace/repository/.git
  REPOSITORY_URL=file:///tmp/source.git /usr/local/bin/clone-repository
'

docker run --rm --read-only \
  --workdir /tmp \
  --tmpfs /workspace:rw,mode=1777 \
  --tmpfs /run:rw,mode=1777,size=64m \
  --tmpfs /tmp:rw,mode=1777,size=64m \
  --env 'AUTHORIZED_KEYS=ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAITestOnlyKey image-test' \
  --env GIT_USER_NAME='Image Test' \
  --env GIT_USER_EMAIL=image-test@ilosia.invalid \
  --entrypoint sh "$image" -c '
    set -eu
    /usr/local/bin/ilosia-workspace-entrypoint &
    server=$!
    sleep 2
    kill "$server"
    wait "$server" || test "$?" = 143
    test -s /workspace/ssh-host-keys/ssh_host_ed25519_key
    test "$(git config --global user.name)" = "Image Test"
  '

echo 'PASS: Agent Workspace image tools, clone safety and non-root SSH entrypoint are valid.'
