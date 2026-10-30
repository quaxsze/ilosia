# Agent Workspace chart

Ce chart déploie un workspace SSH non-root avec un dépôt Git et un `$HOME`
persistants. Warpgate est le seul point d'entrée réseau autorisé ; les sorties
sont limitées au DNS et à HTTPS public.

## Développement local

```bash
./scripts/test_agent_workspace_chart.sh
AW2_SSO_USERNAME=alos ./scripts/install_agent_workspace_aw2.sh \
  https://github.com/quaxsze/ilosia.git
./scripts/check_agent_workspace_aw2.sh
```

Connexion via Warpgate :

```bash
ssh -p 2222 \
  -o PreferredAuthentications=keyboard-interactive \
  -o PubkeyAuthentication=no \
  -o PasswordAuthentication=no \
  'alos:aw2-workspace@127.0.0.1'
```

Codex doit utiliser `danger-full-access` : Kubernetes est le sandbox réel, car
les user namespaces nécessaires à `workspace-write` ne sont pas disponibles
dans un Pod PSS restricted. Utiliser `codex login --device-auth` ou une clé API,
car le port forwarding SSH est désactivé.

`mise`, `uv` et les paquets npm globaux installent leurs fichiers sous
`/workspace/home`, donc sur le PVC. Il n'y a volontairement ni `sudo` ni `apt`
dans une session utilisateur.

Le pipeline publie l'image multi-architecture sous
`ghcr.io/quaxsze/ilosia-agent-workspace:<commit-sha>`.
