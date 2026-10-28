# GitOps local

Le dossier `gitops/` est l'état déclaratif de l'environnement `dev`, suivi dans
`https://github.com/quaxsze/ilosia`. Le Secret `ilosia-secrets` et
`grafana-admin` restent externes à Git ; ils doivent exister avant la première
synchronisation. L'environnement
`dev` active Keycloak/OIDC, donc le Secret applicatif doit aussi contenir les
trois clés `OIDC_RP_CLIENT_SECRET`, `KEYCLOAK_ADMIN_PASSWORD` et
`KEYCLOAK_POSTGRES_PASSWORD` de `k8s/bootstrap/secret.example.yaml`.

```bash
helm repo add argo https://argoproj.github.io/argo-helm
helm repo update
helm upgrade --install argocd argo/argo-cd --version 10.11.6 \
  --namespace argocd --create-namespace --wait --timeout 10m

kubectl apply -f gitops/bootstrap/root.yaml
kubectl get applications --namespace argocd
```

Après une CI réussie sur `main`, le workflow de publication pousse l'image GHCR
taggée avec le SHA testé puis modifie uniquement `gitops/dev/values.yaml`. Argo CD
observe ce commit et synchronise le cluster ; le workflow n'appelle jamais Helm
ou kubectl sur l'environnement.

