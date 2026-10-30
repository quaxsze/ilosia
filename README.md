# Ilosia

Plateforme self-service pour lancer des environnements de développement à la
demande. Les milestones 0 à 18 couvrent l'application Django, les workloads
Jupyter sur Kubernetes, Garage
pour S3, l'observabilité, la CI/CD, la sécurité, GitOps, Keycloak et un module
Terraform Scaleway. Django Auth reste disponible quand OIDC est désactivé.

## Prérequis

- Python 3.12+
- [uv](https://docs.astral.sh/uv/)
- Docker avec Docker Compose
- `kubectl`, `helm` et `k3d` pour Kubernetes local

## Démarrage avec Docker

```bash
cp .env.example .env
docker compose up --build -d
docker compose exec web python manage.py createsuperuser
```

PostgreSQL est publié sur le port hôte `55432` afin de ne pas entrer en conflit
avec une éventuelle installation locale sur le port standard `5432`.
Les migrations sont exécutées par le service Compose éphémère `migrate` avant le
démarrage de Gunicorn.

Ouvrir <http://127.0.0.1:8000/> puis se connecter avec le compte créé.
Si le port `8000` est déjà utilisé, changer `DJANGO_PORT` dans `.env` (par
exemple `DJANGO_PORT=8001`) et utiliser ce port dans l'URL.

La migration initialise JupyterLab dans le catalogue. L'interface reste
consultable avec Docker Compose, mais le lancement réel nécessite que Django soit
déployé dans Kubernetes avec son ServiceAccount.

## Développement local

```bash
docker compose up -d postgres
uv sync
uv run --env-file .env python manage.py migrate
uv run --env-file .env python manage.py runserver
```

## Vérifications

```bash
uv run --env-file .env python manage.py check
uv run --env-file .env python manage.py test
uv run ruff check .
uv run ruff format --check .
```

Le healthcheck est disponible sur <http://127.0.0.1:8000/healthz/>.

## Agent Workspace — AW0

Le spike d'architecture Agent Workspace se prépare localement sans modifier
Django :

```bash
brew install herdr
./scripts/setup_agent_workspace_aw0.sh
```

La première exécution demande le mot de passe administrateur Warpgate. Warpgate
demande ensuite la création unique d'un token API dans son interface ; le script
affiche la procédure exacte et la relance converge tout le socle local.

Consigner ensuite les mesures dans
[`spikes/agent-workspace/AW0_REPORT.md`](spikes/agent-workspace/AW0_REPORT.md).

Le dernier test AW0 configure un client Keycloak temporaire et vérifie le
back-channel logout de bout en bout :

```bash
./scripts/configure_agent_workspace_aw0_oidc.sh <keycloak-username>
./scripts/check_agent_workspace_aw0_logout.sh <keycloak-username>
```

La procédure interactive minimale (première connexion SSO et session SSH à
révoquer) est détaillée dans le rapport AW0.
La configuration k3d publie désormais le port SSH 2222, mais cette modification
ne s'applique à un cluster existant qu'après sa recréation. Ne pas supprimer le
cluster actuel sans avoir sauvegardé ou explicitement accepté la perte de ses
PVC `local-path`.

## Arrêt

```bash
docker compose down
```

Les données PostgreSQL restent dans le volume Docker `postgres_data`.

## Kubernetes local avec k3d

Le déploiement utilise K3s `v1.35.5-k3s1` dans k3d, avec Traefik désactivé.
Helm installe le contrôleur NGINX maintenu par F5/NGINX et le chart applicatif
`charts/ilosia`. Les manifests `k8s/bootstrap` restent la référence
manuelle du Milestone 3 et ne doivent plus être appliqués par-dessus la release.

Installer les outils manquants sur macOS :

```bash
brew install k3d kubectl helm
```

Créer le cluster puis installer NGINX Ingress Controller :

```bash
k3d cluster create --config k8s/bootstrap/k3d.yaml

helm upgrade --install nginx-ingress \
  oci://ghcr.io/nginx/charts/nginx-ingress \
  --version 2.8.0 \
  --namespace nginx-ingress \
  --create-namespace \
  --set controller.service.type=LoadBalancer

kubectl wait --namespace nginx-ingress \
  --for=condition=Ready pod \
  --selector=app.kubernetes.io/instance=nginx-ingress \
  --timeout=180s
```

La procédure Agent Workspace et Warpgate se trouve dans
[`gitops/README.md`](gitops/README.md). Les certificats, backups et autres
secrets locaux qu'elle génère ne doivent jamais être ajoutés à Git.

Si le cluster existe déjà mais n'apparaît pas dans `kubectl`, importer son
contexte local :

```bash
k3d kubeconfig merge ilosia \
  --kubeconfig-merge-default \
  --kubeconfig-switch-context
```

Construire l'image et l'importer dans le cluster :

```bash
docker build -t ilosia:dev .
k3d image import ilosia:dev --cluster ilosia
```

Créer le secret local avant le premier déploiement. Le fichier `secret.yaml` est
ignoré par Git :

```bash
cp k8s/bootstrap/secret.example.yaml k8s/bootstrap/secret.yaml
```

Remplacer toutes les valeurs dans `secret.yaml`, puis installer Ilosia :

```bash
kubectl apply -f k8s/bootstrap/namespace.yaml
kubectl apply -f k8s/bootstrap/secret.yaml

helm upgrade --install ilosia charts/ilosia \
  --namespace ilosia \
  --wait \
  --timeout 5m
```

Le hook Helm exécute les migrations après chaque installation ou upgrade. Le
Secret reste extérieur à Helm et le PVC PostgreSQL porte une
politique `keep` afin qu'une désinstallation ne supprime pas les données.

Le Pod Django embarque Helm et utilise le ServiceAccount
`ilosia-web`. Son RBAC est limité à la création de namespaces et à la
gestion des ressources nécessaires aux charts utilisateurs; il n'est pas
`cluster-admin`.

Créer un compte administrateur :

```bash
kubectl exec --namespace ilosia deployment/ilosia-web \
  -- python manage.py createsuperuser
```

Ouvrir <http://ilosia.localhost:8080/>, se connecter, choisir JupyterLab,
puis sélectionner CPU, mémoire et stockage. Le premier lancement peut prendre
environ une minute pendant le téléchargement de l'image officielle
`quay.io/jupyter/minimal-notebook:2026-07-28`.

Django crée un namespace par utilisateur et un PVC par service, installe
`charts/jupyter`, attend que le Pod soit prêt puis affiche les actions **Open**,
**Logs**, **Stop** et **Delete service and data**. L'URL d'ouverture contient un
token Jupyter dérivé côté serveur; ce token n'est pas stocké dans PostgreSQL.

L'état et les 200 dernières lignes de logs sont lus depuis l'API Kubernetes avec
le ServiceAccount du Pod Django. HTMX rafraîchit ces blocs toutes les cinq
secondes. **Stop** désinstalle la release mais conserve son PVC et son Secret;
**Restart** les réutilise. **Delete service and data** supprime explicitement la
release, le PVC et le Secret tout en conservant l'historique Django.

Le formulaire de lancement accepte des variables normales et secrètes au format
`NAME=value`, une par ligne. Les variables normales sont conservées en base. Pour
les secrets, Django ne conserve que le nom : la valeur est envoyée directement à
un Secret Kubernetes externe à Helm, injectée avec `secretKeyRef`, masquée dans
l'interface, conservée pendant un arrêt et supprimée avec les données du service.

La couche S3 compatible fournit un bucket et une clé Garage limités à
`user-<id>` par utilisateur, la page `/storage/`, des téléchargements par URL
présignée et la suppression d'objets.
Garage tourne en mono-nœud local avec un PVC et expose son API S3 sur
<http://garage.localhost:8080/>. La clé plateforme et le token administrateur
sont lus depuis `ilosia-secrets`, jamais depuis les values Helm. Garage crée une
clé par utilisateur, ensuite copiée uniquement dans les Secrets Kubernetes de
ses services.

Avec deux Jupyter actifs pour le même utilisateur, vérifier automatiquement le
partage S3 et l'isolation de leurs PVC :

```bash
./scripts/check_jupyter_storage.sh user-1
```

Le script installe temporairement `boto3` dans les Pods si nécessaire, utilise
des fichiers de test uniques, puis les supprime.

Avec au moins un Jupyter actif pour un second utilisateur, vérifier en plus que
sa clé ne peut pas accéder au bucket du premier :

```bash
./scripts/check_jupyter_storage.sh user-1 user-2
```

Le mode E2E ne dépend d'aucun utilisateur existant : il crée deux utilisateurs
Django non connectables, deux Jupyter pour le premier et un pour le second. Il
teste les PVC, le partage S3, l'isolation S3 dans les deux sens, puis supprime
les services, volumes, Secrets, buckets, clés, namespaces et utilisateurs :

```bash
./scripts/check_jupyter_storage.sh --e2e
```

Le lancement est synchrone pendant ce milestone. Une file de tâches sera ajoutée
uniquement si les opérations deviennent trop longues pour les workers web.

## Observabilité

Créer le secret administrateur Grafana, puis installer les trois charts épinglés :

```bash
kubectl create namespace monitoring --dry-run=client -o yaml | kubectl apply -f -
kubectl create secret generic grafana-admin --namespace monitoring \
  --from-literal=admin-user=admin \
  --from-literal=admin-password='<mot-de-passe>'

helm upgrade --install monitoring \
  oci://ghcr.io/prometheus-community/charts/kube-prometheus-stack \
  --version 92.10.0 --namespace monitoring \
  --values observability/kube-prometheus-stack-values.yaml \
  --wait --timeout 10m

helm repo add grafana https://grafana.github.io/helm-charts
helm repo update
helm upgrade --install loki grafana/loki --version 7.5.0 \
  --namespace monitoring --values observability/loki-values.yaml \
  --wait --timeout 10m
helm upgrade --install alloy grafana/alloy --version 1.14.3 \
  --namespace monitoring --values observability/alloy-values.yaml \
  --wait --timeout 10m
```

Grafana est disponible sur <http://grafana.localhost:8080/>. Son dashboard
`Ilosia` est chargé automatiquement et Loki apparaît dans **Explore**. Le
mot de passe local peut être relu sans l'inscrire dans le dépôt :

```bash
kubectl get secret grafana-admin --namespace monitoring \
  --output jsonpath='{.data.admin-password}' | base64 -d; echo
```

Prometheus collecte `/metrics`, notamment les compteurs de lancement, d'échec
et de suppression. Alloy lit les logs des Pods par l'API Kubernetes et les
envoie à Loki. Ces composants sont mono-réplique et dimensionnés pour k3d. Le
webhook d'admission Prometheus est désactivé localement pour éviter une
dépendance circulaire entre ses certificats et les hooks Argo CD.

## CI, GHCR et GitOps

Le workflow `.github/workflows/ci.yml` lance Ruff, les tests Django, le lint des
charts et un build Docker. Après une CI réussie sur `main`,
`.github/workflows/publish.yml` publie dans GHCR une image taggée avec le SHA
testé, puis met à jour `gitops/dev/values.yaml`. Il ne déploie jamais directement
avec `kubectl` ou Helm.

Le dépôt GitOps cible `https://github.com/quaxsze/ilosia`. Avant le bootstrap
Argo CD, créer les Secrets applicatif et Grafana hors de Git. Les commandes et
les limites sont détaillées dans
[`gitops/README.md`](gitops/README.md).

## Keycloak et OIDC

Keycloak est optionnel dans le chart afin de préserver le démarrage Django Auth.
Pour activer le realm, le client confidentiel, les rôles `user`/`admin` et le
mapping du `sub` OIDC :

```bash
helm upgrade --install ilosia charts/ilosia \
  --namespace ilosia \
  --set keycloak.enabled=true \
  --set authentication.oidc.enabled=true \
  --wait --timeout 5m
```

Ouvrir ensuite <http://ilosia.localhost:8080/login/> et choisir **Login
with Keycloak**. Keycloak est exposé sur
<http://keycloak.localhost:8080/>. Créer les utilisateurs dans le realm
`ilosia`; le groupe `users` est attribué par défaut et le rôle de realm
`admin` donne les droits administrateur Django.

L'import de realm de Keycloak n'écrase pas un realm déjà présent. Après une
modification structurelle de l'import, appliquer le changement via l'interface
ou l'API d'administration, ou recréer explicitement la base locale.

## Sécurité et quotas

- Django vérifie le propriétaire de chaque service et limite par défaut un
  utilisateur à cinq workloads.
- Chaque namespace utilisateur reçoit un `ResourceQuota`, les labels Pod
  Security `restricted` et un RoleBinding limité à ce namespace.
- Le ServiceAccount de la plateforme peut créer les namespaces, mais ne peut pas
  lire les Secrets du cluster ni créer des workloads dans `default`.
- Les Pods Django et Jupyter sont non privilégiés, sans élévation de privilèges,
  avec les capabilities Linux supprimées.
- Une NetworkPolicy Jupyter n'autorise l'entrée que depuis NGINX Ingress.

Ces barrières complètent la validation applicative ; elles ne remplacent pas une
revue de sécurité avant une exposition publique.

## Infrastructure Terraform

Le module [`terraform/scaleway`](terraform/scaleway/README.md) crée un réseau
privé, un cluster Kapsule et un pool de workers. Il ne déploie ni Ilosia ni
les workloads utilisateurs : cette responsabilité reste à Helm et Argo CD.
`terraform validate` fonctionne sans credentials, mais `plan` et `apply`
nécessitent un compte Scaleway et créent des ressources facturées.

### Vérifications Kubernetes

```bash
helm lint charts/ilosia
helm template ilosia charts/ilosia --namespace ilosia
helm status ilosia --namespace ilosia
helm history ilosia --namespace ilosia
kubectl get pods,services,ingress,pvc --namespace ilosia
curl --fail http://ilosia.localhost:8080/healthz/
```

Valider le chart Jupyter sans révéler de vrai token :

```bash
helm lint charts/jupyter \
  --set ingress.host=jupyter-test.localhost

helm list --all-namespaces
kubectl get pods,services,ingress,pvc --all-namespaces
```

Les PVC Jupyter portent eux aussi la politique `keep`. Une release peut aussi
être supprimée manuellement avec :

```bash
helm uninstall <release> --namespace <user-namespace>
```

Pour vérifier la persistance de PostgreSQL, créer des données depuis
l'application, supprimer son Pod, attendre sa recréation puis vérifier que les
données sont toujours présentes :

```bash
kubectl delete pod --namespace ilosia \
  --selector=app.kubernetes.io/name=postgres
kubectl rollout status deployment/postgres \
  --namespace ilosia --timeout=120s
```

Supprimer le cluster, y compris son volume PostgreSQL :

```bash
k3d cluster delete ilosia
```

Pour supprimer seulement la release, le PVC est conservé :

```bash
helm uninstall ilosia --namespace ilosia
kubectl get pvc --namespace ilosia
```

La suppression des données reste une action séparée et explicite :

```bash
kubectl delete pvc postgres-data --namespace ilosia
```

