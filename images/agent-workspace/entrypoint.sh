#!/bin/sh
set -eu
umask 077

: "${AUTHORIZED_KEYS:?AUTHORIZED_KEYS is required}"

mkdir -p \
  "$HOME/.cache" \
  "$HOME/.config" \
  "$HOME/.local/bin" \
  "$HOME/.local/share/mise" \
  "$HOME/.ssh" \
  /workspace/repository \
  /workspace/ssh-host-keys \
  /run/sshd

printf '%s\n' "$AUTHORIZED_KEYS" >"$HOME/.ssh/authorized_keys"
chmod 0700 "$HOME"
chmod 0700 "$HOME/.ssh"
chmod 0600 "$HOME/.ssh/authorized_keys"

for key_type in ed25519 rsa; do
  key_path="/workspace/ssh-host-keys/ssh_host_${key_type}_key"
  if [ ! -f "$key_path" ]; then
    ssh-keygen -q -N '' -t "$key_type" -f "$key_path"
  fi
  chmod 0600 "$key_path"
done

if ! git config --global user.name >/dev/null 2>&1 && [ -n "${GIT_USER_NAME:-}" ]; then
  git config --global user.name "$GIT_USER_NAME"
fi
if ! git config --global user.email >/dev/null 2>&1 && [ -n "${GIT_USER_EMAIL:-}" ]; then
  git config --global user.email "$GIT_USER_EMAIL"
fi

exec /usr/sbin/sshd -D -e -f /etc/ssh/sshd_config_ilosia
