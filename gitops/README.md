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
`warpgate-data`. Les Secrets locaux créés pendant AW0 restent externes à Git :

- `warpgate-aw0/adminPassword` initialise l'administrateur ;
- `warpgate-aw0-config/warpgate.yaml` contient la configuration OIDC ;
- `warpgate-aw0-api/token` sert aux scripts d'administration ;
- `warpgate-aw0-oidc/clientSecret` conserve le secret du client Keycloak.

Avant la première synchronisation d'un cluster local neuf, les créer avec la
procédure AW0. Sur le cluster de développement existant, Argo CD adopte le
Service, le Deployment et le PVC déjà présents sans recréer les Secrets ni les
données. Le renommage des Secrets, l'Ingress avec CA fiable, le chiffrement au
repos et la sauvegarde/restauration appartiennent à la tranche AW1 suivante.

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

