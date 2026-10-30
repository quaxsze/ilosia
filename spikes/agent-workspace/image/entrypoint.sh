#!/bin/sh
set -eu

: "${AUTHORIZED_KEYS:?AUTHORIZED_KEYS is required}"

mkdir -p "$HOME/.ssh" /workspace/ssh-host-keys /run/sshd
chmod 0700 "$HOME/.ssh"
printf '%s\n' "$AUTHORIZED_KEYS" >"$HOME/.ssh/authorized_keys"
chmod 0600 "$HOME/.ssh/authorized_keys"

for key_type in ed25519 rsa; do
  key_path="/workspace/ssh-host-keys/ssh_host_${key_type}_key"
  if [ ! -f "$key_path" ]; then
    ssh-keygen -q -N '' -t "$key_type" -f "$key_path"
  fi
done

if ! git config --global user.name >/dev/null 2>&1; then
  git config --global user.name "AW0 Developer"
fi
if ! git config --global user.email >/dev/null 2>&1; then
  git config --global user.email "aw0@ilosia.invalid"
fi

exec /usr/sbin/sshd -D -e -f /etc/ssh/sshd_config_aw0
