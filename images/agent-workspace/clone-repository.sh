#!/bin/sh
set -eu

: "${REPOSITORY_URL:?REPOSITORY_URL is required}"
cd /workspace

if [ -e /workspace/repository/.git ]; then
  exit 0
fi

if [ -d /workspace/repository ] && \
  [ -n "$(find /workspace/repository -mindepth 1 -maxdepth 1 -print -quit)" ]; then
  echo "Refusing to replace a non-empty repository directory without .git." >&2
  exit 1
fi

rm -rf /workspace/.clone-tmp
rmdir /workspace/repository 2>/dev/null || true
git clone --filter=blob:none -- "$REPOSITORY_URL" /workspace/.clone-tmp
mv /workspace/.clone-tmp /workspace/repository
