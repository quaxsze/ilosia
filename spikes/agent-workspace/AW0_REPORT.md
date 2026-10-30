# AW0 — Agent Workspace technical spike

Status: **in progress — restricted workspace running**

This spike changes no Django code. It validates the architecture before AW1.
Never paste tokens, passwords, OAuth codes or terminal contents into this file.

## Local setup

Run from the repository root:

```bash
brew install herdr
export AW0_AUTHORIZED_KEYS_FILE="$HOME/.ssh/id_ed25519.pub"
./scripts/setup_agent_workspace_aw0.sh
```

The command is idempotent. It runs the preflight, installs and configures
Warpgate, starts the temporary SSH proxy, builds the workspace, reads
Warpgate's Ed25519 client key, and updates `authorized_keys`.

Warpgate only creates API tokens from its web UI. On the first run, follow the
four instructions printed by the script and rerun it with
`WARPGATE_AW0_API_TOKEN`. A successful run stores that token in the local
Kubernetes Secret `warpgate/warpgate-aw0-api`; it is never written to Git.
Read it silently instead of putting it directly in the command line, so it is
not saved in shell history:

```bash
read -s WARPGATE_AW0_API_TOKEN
export WARPGATE_AW0_API_TOKEN
./scripts/setup_agent_workspace_aw0.sh
unset WARPGATE_AW0_API_TOKEN
```

Observed before the first run:

- host: macOS arm64;
- Codex CLI: `0.165.0`;
- Herdr client: `0.9.5`;
- the existing k3d cluster predates the host mapping `2222:2222`;
- the Codex execution sandbox cannot access the local Docker socket or the
  loopback Kubernetes API, so cluster measurements must be launched from the
  user's terminal.

Do not recreate the current cluster only to satisfy the preflight. Back up or
accept the loss of local-path PVC data first, then use the maintenance command
documented below.

The proxy publishes only the temporary SSH path and can be removed with:

```bash
docker rm --force ilosia-aw0-ssh-proxy
```

If no Ed25519 key exists, generate a dedicated AW0 key first:

```bash
ssh-keygen -t ed25519 -f "$HOME/.ssh/ilosia_aw0" -C ilosia-aw0
export AW0_AUTHORIZED_KEYS_FILE="$HOME/.ssh/ilosia_aw0.pub"
./scripts/setup_agent_workspace_aw0.sh
```

The first goal is deliberately narrow: the Pod must become Ready while using
PSS restricted, a read-only root filesystem and sshd as UID 1000. A failure is
an AW0 result, not something to bypass silently.

## Versions under test

| Component | Client | Server/image | Result |
|---|---|---|---|
| Herdr | 0.9.5 | 0.9.5 | machine bootstrap and remote attach passed |
| Codex CLI | 0.165.0 | 0.165.0 | device auth, file write and local commit passed |
| Warpgate | n/a | 0.30.2 | browser SSH approval passed |
| Warpgate Helm chart | n/a | 0.2.0 | install and upgrade passed |
| Kubernetes | kubectl 1.36.1 | k3s 1.35.5 | workspace running |

### Restricted workspace result

- image build from cold base layers: `109.3s`;
- Warpgate Pod, PVC and LoadBalancer: ready;
- workspace PVC and NetworkPolicy: created;
- public repository download: passed ; its first destination was nested because
  the image working directory pre-created `repository`, then the init container
  was corrected to produce `/workspace/repository/.git` ;
- PSS restricted admission: passed;
- sshd as UID 1000: passed ; TCP probes were replaced by PID probes because
  their empty handshakes polluted the sshd logs ;
- the first restart exposed `fsGroup` changing persistent SSH private keys to
  `0660`; volume preparation now restores `0600` before sshd starts ;
- workspace Pod after correction: `Running`, `1/1`, zero restarts ;
- runtime identity: `uid=1000(developer) gid=1000(developer)` ;
- Herdr server binary: `0.9.5` ;
- Codex CLI server binary: `0.165.0` ;
- repository layout and clean Git status: passed ;
- sshd log after PID probes: one listener line, no probe handshake noise.
- direct OpenSSH authentication through a temporary port-forward: passed ;
- remote command returned UID 1000, Herdr 0.9.5, Codex 0.165.0 and a clean
  repository.
- Warpgate admin API authentication: passed ;
- idempotent creation of the `aw0-workspace` target and role, with bindings to
  the local `admin` user: passed ;
- the local `admin` SSH policy is converged to `WebUserApproval` and verified
  through the Warpgate API ;
- SSH through Warpgate requested one browser approval with a matching security
  key, then executed as `uid=1000(developer)` ;
- Warpgate API token persisted in the local Kubernetes Secret: passed.

The setup keeps the local fallback key, validates Warpgate's key, updates the
Secret and restarts the Pod with the same PVC and SSH host keys. Connect through
the configured target with:

```bash
ssh -p 2222 \
  -o PreferredAuthentications=keyboard-interactive \
  -o PubkeyAuthentication=no \
  -o PasswordAuthentication=no \
  'admin:aw0-workspace@127.0.0.1'
```

This must print an approval URL and a short security key, not ask for the
Warpgate password. Open the URL in a browser already logged into the local
Warpgate UI, compare the key and approve the request.

## 1. Herdr over SSH

Record the number of SSH connections and browser approvals from Warpgate logs.

Sanitized session history can be collected through the Warpgate admin API:

```bash
./scripts/report_agent_workspace_aw0_sessions.sh
```

| Action | Connections | Browser approvals | Result |
|---|---:|---:|---|
| OpenSSH remote command | 1 | 1 | passed |
| `herdr machine add` | 1 | 1 | passed; remote server ready |
| first remote attach | 1 | not separately recorded | passed |
| detach and reattach | 1 | not separately recorded | passed |
| network interruption | TODO | TODO | TODO |
| expired web session | TODO | TODO | TODO |
| client N / server N | TODO | TODO | TODO |
| client N-1 / server N | TODO | TODO | TODO |
| client N / server N-1 | TODO | TODO | TODO |

Pass condition: at most one approval per user and target during the configured
Warpgate approval-cache period.

Warpgate recorded six SSH sessions for the six observed client actions between
16:58 and 17:18 UTC: direct OpenSSH, `machine add`, first attach, reattach, the
long-lived Herdr session, and its replacement after the Pod restart. No Herdr
action fanned out into multiple SSH sessions. Approval caching still needs a
controlled measurement because the two attach prompts were not recorded
separately.

## 2. Codex authentication

Inside the disposable workspace:

```bash
codex login --device-auth
codex login status
```

Then detach, reattach and recreate the Pod with the same PVC.

Result: `codex login --device-auth` passed and `codex login status` returned
`Logged in using ChatGPT`. After replacing the Pod, the PVC identity stayed the
same, Herdr reconnected and Codex remained logged in: passed.

## 3. Codex sandbox

Test in this order:

```bash
codex --sandbox workspace-write --ask-for-approval on-request
codex --sandbox danger-full-access --ask-for-approval on-request
```

Only test the second command if the first one fails under PSS restricted.

| Check | workspace-write | danger-full-access |
|---|---|---|
| read/write repository | failed: `bwrap` cannot create a user namespace | passed |
| `git diff` and local commit | n/a | passed |
| repository tests | TODO | TODO |
| allowed HTTPS egress | n/a | passed |
| paths outside PVC refused | TODO | n/a |

`workspace-write` reached Codex successfully but every spawned command failed
before execution because PSS restricted prevents the unprivileged user namespace
required by `bwrap`; the requested test file was not created.

`danger-full-access` created and read the requested file successfully. The file
was then removed and `git status --short` returned clean.

On a disposable branch, Codex created only the requested file, committed it
with the exact requested message and left a clean worktree. No push occurred;
the original `main` branch was restored and the disposable branch deleted.

Selected mode: `danger-full-access`, with the Kubernetes Pod as the actual
sandbox boundary.

## 4. Launch time and web availability

Run the isolated end-to-end benchmark from the repository root:

```bash
./scripts/benchmark_agent_workspace_aw0.sh
```

It creates a disposable four-node k3d cluster and local registry so cold and
cached pulls are measured on separate nodes without changing the Ilosia cluster
or its PVCs. Results are written to `AW0_BENCHMARK_RESULTS.md`; all disposable
infrastructure is removed afterward.

| Scenario | Duration | `/healthz` available | Result |
|---|---:|---|---|
| cached image, small repository | 6s | n/a | passed |
| cold image, small repository | 17s | n/a | passed |
| cached image, large repository | 42s | n/a | passed |
| cold image, large repository | 50s | n/a | passed |
| invalid repository | 7s | n/a | failure detected |
| two simultaneous cold launches | 20s | passed | passed |

All Kubernetes-side scenarios remained below the 300-second Helm budget. The
local result does not require asynchronous provisioning before AW1. The cold
pull used a local registry and must be repeated against GHCR on Scaleway.

Decision: synchronous remains acceptable for the first integration, with a
mandatory concurrency test through the real Django launch endpoint. The
benchmark only measured shared Docker-host contention; it did not occupy the
two Gunicorn workers. If two concurrent requests make `/healthz` unavailable,
provisioning becomes asynchronous before AW3.

## 5. Egress

Run the reproducible k3d check from the repository root:

```bash
./scripts/check_agent_workspace_aw0_egress.sh
```

| Destination | Expected | k3d | Scaleway |
|---|---|---|---|
| `github.com:443` | allowed | passed | TODO |
| `api.openai.com:443` | allowed | passed | TODO |
| public TCP 80 | denied | passed | TODO |
| `kubernetes.default.svc` | denied | passed | TODO |
| node API address | denied | passed (`172.22.0.3:6443`) | TODO |
| real `api_server_url` and port | denied | TODO | TODO |
| `169.254.42.42` | denied | unreachable | TODO |
| `169.254.169.254` | denied | unreachable | TODO |

The control-plane ACL remains unchanged unless a separate test proves that a
restriction preserves node readiness, Django, Helm and cluster maintenance.

## 6. Keycloak logout

Configure the temporary client and provider for an existing, enabled Keycloak
user whose email is verified:

```bash
./scripts/configure_agent_workspace_aw0_oidc.sh <keycloak-username>
```

If the permanent administrator credentials stored in `ilosia-secrets` are no
longer valid, the local-only recovery script briefly stops the
single Keycloak Pod, creates an official temporary recovery administrator,
creates the permanent administrator `ilosia-admin`, synchronizes its username
and password in `ilosia-secrets`, and removes the temporary user:

```bash
read -s KEYCLOAK_ADMIN_PASSWORD
export KEYCLOAK_ADMIN_PASSWORD
./scripts/recover_local_keycloak_admin.sh
unset KEYCLOAK_ADMIN_PASSWORD
```

It refuses to run outside the `k3d-ilosia` context.

Open <https://localhost:8888/@warpgate>, choose **Keycloak**, and authenticate.
The first login creates the temporary Warpgate user. Run the configuration
command once more to bind it to the AW0 target. Then start a long-lived SSH
command in one terminal:

```bash
ssh -p 2222 \
  -o PreferredAuthentications=keyboard-interactive \
  -o PubkeyAuthentication=no \
  -o PasswordAuthentication=no \
  '<keycloak-username>:aw0-workspace@127.0.0.1' \
  'sleep 600'
```

While it is connected, revoke every Keycloak session for the user and measure
Warpgate's back-channel reaction from a second terminal:

```bash
./scripts/check_agent_workspace_aw0_logout.sh <keycloak-username>
```

The local client is `warpgate-aw0`; its secret and complete Warpgate config are
stored in Kubernetes Secrets, never in Git. AW0 uses k3d split DNS and disables
certificate verification only for Keycloak's outgoing HTTP client because
Warpgate has a self-signed certificate. AW1 replaces that shortcut with a
trusted certificate or CA bundle.

| Action | OIDC web session | Active SSH | Result |
|---|---|---|---|
| Keycloak session revocation | fresh Keycloak login and Warpgate approval required | remained open beyond 20s | limitation documented |

Observed with Warpgate 0.30.2 on 30 October 2026: Keycloak sent the logout token,
Warpgate validated it and logged one matching OIDC session, but the approved
SSH command continued running. A second SSH connection required both a new
`alos` login and a new Warpgate approval, confirming that the web OIDC session
was invalidated.
Administrative deprovisioning must revoke the user's Warpgate role; AW5
verifies that this closes active sessions.

## Maintenance command for the k3d port mapping

The repository configuration now publishes host port 2222. It applies only to
a newly created cluster. Recreating k3d deletes local-path PVC data inside that
cluster, so run this only after an explicit backup or acceptance of data loss:

```bash
k3d cluster delete ilosia
k3d cluster create --config k8s/bootstrap/k3d.yaml
```

Reinstall the existing Ilosia stack before continuing the spike.

## Decision

- [x] Go local for AW1
- [ ] Go production
- [ ] No-Go
- [ ] Provisioning must become asynchronous before AW3
- [ ] TCP 443 alone is sufficient
- [ ] TCP 80 is justified

Decision and evidence: local Kubernetes timing, Herdr, Codex persistence,
sandbox choice, k3d egress and Keycloak logout semantics are documented. A
local launch stays synchronous: the 50-second worst case and the concurrent
health check remain below the current timeouts. Production remains blocked on
the sensitive egress checks on Scaleway and the AW2 toolchain check needed to
decide whether TCP 443 alone is sufficient.
