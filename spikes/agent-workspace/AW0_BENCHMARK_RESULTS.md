# AW0 Agent Workspace benchmark

- Date: 2026-10-29T18:43:31Z
- Image: `ilosia-agent-workspace-aw0:0.1.0`, distributed through an isolated local registry
- Small repository: `https://github.com/quaxsze/ilosia.git`
- Large repository: `https://github.com/kubernetes/kubernetes.git`
- Limit: 300 seconds per launch

| Scenario | Duration | Ilosia /healthz | Result |
|---|---:|---|---|
| cold image + small repository | 17s | n/a | passed |
| cached image + small repository | 6s | n/a | passed |
| cold image + large repository | 50s | n/a | passed |
| cached image + large repository | 42s | n/a | passed |
| invalid repository | 7s | n/a | passed: clone failure detected |
| two simultaneous cold launches | 20s | passed | passed |

The cold scenarios are first pulls from a local registry on distinct k3d nodes.
They measure unpacking and startup accurately but not WAN latency to GHCR.

The concurrent health check observes the existing local Ilosia deployment. It
measures shared Docker-host contention, not Django worker blocking; that must be
retested after the launch endpoint exists.

Worst observed launch: 50s.
