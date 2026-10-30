# GitOps local

Le dossier `gitops/` est l'état déclaratif de l'environnement `dev`, suivi dans
`https://github.com/quaxsze/ilosia`. Le Secret `ilosia-secrets` et
`grafana-admin` restent externes à Git ; ils doivent exister avant la première
synchronisation. L'environnement
`dev` active Keycloak/OIDC, donc le Secret applicatif doit aussi contenir les
quatre clés `OIDC_RP_CLIENT_SECRET`, `KEYCLOAK_ADMIN_USERNAME`,
`KEYCLOAK_ADMIN_PASSWORD` et
`KEYCLOAK_POSTGRES_PASSWORD` de `k8s/bootstrap/secret.example.yaml`.

L'application `warpgate` utilise le chart OCI officiel `0.2.0`, l'image
Warpgate `0.30.2` et les values suivies dans
`gitops/dev/warpgate-values.yaml`. Ses données SQLite restent sur le PVC
`warpgate-data`. Les Secrets AW1 restent externes à Git :

- `warpgate-secrets` contient le mot de passe initial, le secret OIDC, le token
  d'administration et la clé de chiffrement au repos ;
- `warpgate-tls` contient le certificat de service ;
- `warpgate-tls-ca` contient la CA locale et sa clé de renouvellement ;
- `ilosia/warpgate-ca` fournit uniquement le certificat public à Keycloak.

### Migration AW1 locale

Préparer les Secrets définitifs avant de publier les values qui les
référencent. La configuration non secrète est déclarée dans Git ; le chart y
substitue le secret OIDC au démarrage. Le script conserve les valeurs AW0
existantes, génère une seule clé de chiffrement et une CA locale, met à jour le
client Keycloak, puis rend le split-DNS k3d stable malgré la réconciliation
Argo CD :

```bash
./scripts/prepare_agent_workspace_aw1.sh
git add \
  .github/workflows/ci.yml .gitignore README.md \
  charts/ilosia gitops \
  scripts/prepare_agent_workspace_aw1.sh \
  scripts/start_agent_workspace_aw1_https_proxy.sh \
  scripts/check_agent_workspace_aw1.sh \
  scripts/backup_warpgate.sh scripts/test_restore_warpgate.sh \
  scripts/finalize_agent_workspace_aw1.sh
git commit -m "feat: secure Warpgate deployment"
git pull --rebase
git push

kubectl get applications --namespace argocd --watch
./scripts/prepare_agent_workspace_aw1.sh
./scripts/check_agent_workspace_aw1.sh
```

Quand `ilosia` et `warpgate` sont `Synced/Healthy`, démarrer le proxy HTTPS et
vérifier le certificat sans modifier le trousseau système :

```bash
./scripts/start_agent_workspace_aw1_https_proxy.sh
curl --cacert .local/warpgate/ca.crt \
  https://warpgate.localhost:8443/@warpgate/
```

Pour utiliser le navigateur sans avertissement sur macOS, installer
explicitement la CA locale. Cette commande modifie le trousseau système et
demande le mot de passe administrateur :

```bash
sudo security add-trusted-cert -d -r trustRoot \
  -k /Library/Keychains/System.keychain \
  .local/warpgate/ca.crt
```

Valider ensuite une connexion Keycloak et une connexion SSH approuvée dans le
navigateur.

### Sauvegarde et restauration Warpgate

Le backup réalise une copie SQLite cohérente à chaud et conserve aussi les
enregistrements, la configuration, les certificats, l'image exacte et la clé
de chiffrement. L'archive contient des secrets et reste ignorée par Git avec
des permissions `0600` :

```bash
./scripts/backup_warpgate.sh backups/warpgate/aw1.tar.gz
./scripts/test_restore_warpgate.sh backups/warpgate/aw1.tar.gz
```

Le test restaure dans `warpgate-restore-test`, attend que Warpgate soit sain,
puis supprime ce namespace. Après ce test et une dernière connexion réelle,
retirer les copies AW0 devenues inutiles :

```bash
./scripts/finalize_agent_workspace_aw1.sh
```

Sur un cluster local neuf, exécuter d'abord AW0 pour créer le compte et le
client OIDC, puis cette migration. Une installation vierge directement depuis
AW1 sera ajoutée quand le provisioning Django remplacera ces scripts de spike.

```bash
helm repo add argo https://argoproj.github.io/argo-helm
helm repo update
helm upgrade --install argocd argo/argo-cd --version 10.11.6 \
  --namespace argocd --create-namespace --wait --timeout 10m

kubectl apply -f gitops/bootstrap/root.yaml
kubectl get applications --namespace argocd
```

Vérifier l'adoption de Warpgate :

```bash
kubectl get application warpgate --namespace argocd
kubectl get pods,pvc,service --namespace warpgate
```

Après une CI réussie sur `main`, le workflow de publication pousse l'image GHCR
taggée avec le SHA testé puis modifie uniquement `gitops/dev/values.yaml`. Argo CD
observe ce commit et synchronise le cluster ; le workflow n'appelle jamais Helm
ou kubectl sur l'environnement.

