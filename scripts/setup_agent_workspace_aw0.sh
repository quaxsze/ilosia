#!/bin/sh
set -eu

repository_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$repository_root"

./scripts/check_agent_workspace_aw0.sh

if ! kubectl get secret warpgate-aw0 --namespace warpgate >/dev/null 2>&1 && \
  [ -z "${WARPGATE_AW0_ADMIN_PASSWORD:-}" ]; then
  printf 'Warpgate admin password: ' >&2
  stty -echo
  trap 'stty echo' EXIT INT TERM
  IFS= read -r WARPGATE_AW0_ADMIN_PASSWORD
  stty echo
  trap - EXIT INT TERM
  printf '\n' >&2
  export WARPGATE_AW0_ADMIN_PASSWORD
fi

./scripts/install_agent_workspace_aw0_warpgate.sh
./scripts/configure_agent_workspace_aw0_warpgate.sh
./scripts/start_agent_workspace_aw0_ssh_proxy.sh
./scripts/install_agent_workspace_aw0_workload.sh
./scripts/set_agent_workspace_aw0_warpgate_key.sh

cat <<'EOF'

Agent Workspace AW0 local is ready.
Connect through Warpgate and approve the request in your logged-in browser:
  ssh -p 2222 -o PreferredAuthentications=keyboard-interactive -o PubkeyAuthentication=no -o PasswordAuthentication=no 'admin:aw0-workspace@127.0.0.1'
EOF
