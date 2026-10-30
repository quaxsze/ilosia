# Agent Workspace — plan d'architecture

Statut : plan de référence avant implémentation
Date : 29 octobre 2026

## 1. Objectif

Ajouter au catalogue Ilosia un service **Agent Workspace** : un environnement de
développement distant et persistant dans lequel un utilisateur authentifié peut :

1. cloner un dépôt Git ;
2. se connecter avec Herdr par SSH ;
3. lancer Codex dans le dépôt ;
4. modifier et committer des fichiers ;
5. se déconnecter sans arrêter les processus ;
6. arrêter puis redémarrer le calcul en conservant les données ;
7. supprimer explicitement le workspace et son PVC.

La V1 repose sur :

- Keycloak pour l'identité ;
- Warpgate pour l'authentification et le routage SSH ;
- Kubernetes pour l'isolation et le calcul ;
- un PVC par workspace pour les fichiers et le home utilisateur ;
- Herdr pour les terminaux persistants ;
- Codex CLI comme agent de développement ;
- Git pour l'historique local.

## 2. Périmètre de la V1

### Inclus

- un workspace par `ServiceInstance` ;
- un dépôt GitHub public par workspace ;
- URL de la forme `https://github.com/<owner>/<repository>[.git]` ;
- commits Git locaux ;
- CPU, mémoire et stockage configurables ;
- Herdr et Codex préinstallés ;
- authentification Codex par Device Auth ou clé API fournie par l'utilisateur ;
- accès SSH exclusivement via Warpgate ;
- authentification Keycloak obligatoire ;
- actions Stop, Restart et Delete service and data ;
- isolation réseau entre utilisateurs ;
- logs Kubernetes ;
- compteurs Prometheus existants ;
- logs applicatifs structurés.

### Hors périmètre

- dépôts privés ;
- `git push` automatisé ;
- GitHub App ;
- partage d'un workspace entre plusieurs utilisateurs ;
- Docker-in-Docker ou montage de la socket Docker ;
- accès root dans le workspace ;
- GPU ;
- installation de paquets système avec `apt` à l'exécution ;
- processus survivant à l'arrêt ou au remplacement du Pod ;
- opérateur Kubernetes Warpgate ;
- Vault ou OpenBao ;
- enregistrement complet des terminaux ;
- injection automatique du bucket S3 personnel ;
- nouveau module d'audit applicatif ;
- provisionnement multi-cluster.

## 3. Décisions d'architecture

1. Réutiliser `ServiceInstance` et ajouter uniquement un champ nullable
   `repository_url`.
2. Ne pas créer de modèle `AgentWorkspace` ou `RemoteAccessIdentity` en V1.
3. Dériver tous les noms Warpgate et Kubernetes de façon déterministe.
4. Retrouver les ressources Warpgate par leur nom avec des opérations
   `ensure_*` idempotentes ; ne pas stocker leurs IDs.
5. Exécuter les opérations Warpgate à chaque Launch et Restart.
6. Ne faire aucun appel Warpgate pendant Stop.
7. Conserver la target Warpgate pendant Stop et la supprimer seulement pendant
   Delete.
8. Faire pointer la target vers le DNS stable du Service Kubernetes, jamais vers
   son ClusterIP.
9. Passer les clés publiques Warpgate comme values Helm communes ; une clé
   publique n'est pas un Secret.
10. Utiliser un `Deployment` à une réplique avec stratégie `Recreate`, pas un
    `StatefulSet`.
11. Garder deux branches explicites, Jupyter et Agent Workspace, plutôt que
    créer un système générique de plugins.
12. Conserver une seule réplique Warpgate en V1.
13. Garder le lancement synchrone seulement si AW0 prouve que le pire cas
    supporté reste sous les timeouts actuels sans monopoliser les workers web.
14. Ne pas ajouter de labels aux compteurs Prometheus existants en V1.

## 4. Architecture générale

```text
                            Internet
                               |
                 +-------------+-------------+
                 |                           |
              HTTPS                        SSH
                 |                           |
                 v                           v
          NGINX Ingress              Warpgate :2222
                 |                           |
        +--------+--------+                  |
        |                 |                  |
        v                 v                  |
     Ilosia            Keycloak              |
     Django              OIDC                |
        |                                     |
        | Helm + Kubernetes API               |
        v                                     |
  namespace user-42                           |
  +-------------------------------------------+
  |
  v
Agent Workspace
├── Deployment, 1 Pod
├── Service ClusterIP :2222
├── PVC
│   ├── home/
│   ├── repository/
│   └── ssh-host-keys/
├── sshd non-root
├── Herdr
├── Codex CLI
└── Git et toolchains
```

## 5. Répartition des responsabilités

| Composant | Responsabilité |
|---|---|
| Keycloak | Authentifier et imposer la vérification de l'email |
| Django | Vérifier les quotas et la propriété, orchestrer le cycle de vie |
| Warpgate | Authentifier la connexion SSH, autoriser et router vers la target |
| Kubernetes | Isoler et exécuter le workspace |
| PVC | Conserver le dépôt, les commits, le home et les clés hôte SSH |
| Herdr | Conserver et organiser les terminaux et agents pendant la vie du Pod |
| Codex | Lire et modifier le dépôt, exécuter commandes et tests |
| Git | Conserver branches, changements et commits locaux |

Keycloak ne contient aucun groupe par workspace. Ilosia reste la source de
vérité pour la propriété des services.

## 6. Expérience utilisateur

### Lancement

Le catalogue contient une carte `Agent Workspace`. Le formulaire demande :

- nom du service ;
- URL GitHub publique ;
- CPU ;
- mémoire ;
- stockage.

Il ne propose pas encore de variables arbitraires ou de secrets.

### Page de détail

La page affiche :

- statut global ;
- dépôt ;
- ressources ;
- namespace et release Helm ;
- configuration SSH à copier ;
- commande Herdr ;
- instruction `codex login --device-auth` ;
- avertissement sur la persistance des processus ;
- actions Logs, Stop, Restart et Delete service and data.

Actions pour Agent Workspace :

| Statut | Actions principales |
|---|---|
| `RUNNING` | Logs, Stop, Delete |
| `UNKNOWN` | Logs, Stop, Restart, Delete |
| `FAILED` | Logs, Restart, Delete |
| `STOPPED` | Restart, Delete |
| `INSTALLING`, `STOPPING`, `DELETING` | actions mutantes désactivées |

Après Launch, afficher un message de succès uniquement pour `RUNNING`.
`FAILED` et `UNKNOWN` affichent une erreur avec les actions de réparation.

Le composant d'actions étant partagé, il doit aussi vérifier le slug du
service. Jupyter conserve son comportement actuel : Restart est proposé
uniquement pour `STOPPED`. Les nouveaux boutons Restart de `FAILED` et
`UNKNOWN` sont réservés à `agent-workspace`.

Exemple de configuration :

```sshconfig
Host ilosia-project-9a1c
    HostName ssh.ilosia.example
    Port 2222
    User u-42:aw-9a1c...
```

Puis :

```bash
herdr machine add ilosia-project-9a1c
herdr --remote ilosia-project-9a1c
```

## 7. Modèle de données

Ajouter à `ServiceInstance` :

```text
repository_url  URLField(blank=True)
```

Règles :

- vide pour Jupyter ;
- obligatoire pour `agent-workspace` ;
- validé dans le formulaire et à la frontière du service ;
- conservé après suppression pour l'historique ;
- jamais utilisé directement comme argument shell.

Tous les noms externes sont déterministes :

```text
Release Kubernetes : agent-<service UUID sans tirets>
Service Kubernetes : agent-<service UUID sans tirets>
Target Warpgate    : aw-<service UUID sans tirets>
User Warpgate      : u-<Django user id>
Role Warpgate      : ilosia-user-<Django user id>
Namespace          : user-<Django user id>
```

La target utilise :

```text
agent-<hex>.user-<id>.svc.cluster.local:2222
```

Le ClusterIP n'est jamais stocké ni envoyé à Warpgate.

## 8. Validation du dépôt

La V1 accepte uniquement :

```text
https://github.com/<owner>/<repository>
https://github.com/<owner>/<repository>.git
```

Refuser :

- tout autre schéma ;
- tout autre hôte ;
- username ou password dans l'URL ;
- adresse IP ;
- port explicite ;
- query string ou fragment ;
- chemin contenant `..` ;
- nom owner/repository invalide.

Cette limitation réduit le risque SSRF au lancement. L'agent reste considéré
comme capable d'émettre du trafic vers toute destination autorisée par la
NetworkPolicy.

Le clone est exécuté sans shell :

```text
git clone --filter=blob:none -- <url> /workspace/.clone-tmp
mv /workspace/.clone-tmp /workspace/repository
```

Règles d'idempotence :

- si `/workspace/repository/.git` existe, ne pas cloner et ne pas faire de pull ;
- nettoyer seulement le dossier temporaire créé par l'init container ;
- ne jamais supprimer automatiquement un dépôt existant ;
- limiter le clone à une durée inférieure au timeout Helm ;
- conserver changements non commités, branches et commits au Restart.

## 9. Identité Keycloak

### Règles du realm

La garantie de confiance de l'email vient de Keycloak :

- email obligatoire ;
- `duplicateEmailsAllowed=false` ;
- email en lecture seule pour l'utilisateur en V1 ;
- action `VERIFY_EMAIL` obligatoire ;
- claim `email_verified=true` dans les tokens ;
- réauthentification administrative nécessaire avant toute modification ;
- pas d'auto-inscription.

Le backend Django vérifie déjà `email_verified is True` dans
`accounts/backends.py`.

En développement sans SMTP, un administrateur peut marquer manuellement
l'adresse comme vérifiée. En production, la vérification doit utiliser l'email.

Une évolution pourra activer `UPDATE_EMAIL` avec réauthentification et
vérification de la nouvelle adresse avant mutation.

### Cycle de vie de l'identité

Warpgate rattache le SSO par email alors que Django rattache Keycloak par
`sub`. Une adresse réattribuée alors que son ancien credential Warpgate existe
donnerait accès à l'ancien compte avant même un appel à Django. La V1 applique
donc les protections suivantes :

- aucun compte Ilosia ordinaire, y compris applicativement `admin`, ne reçoit
  de rôle d'administration Keycloak ; un compte break-glass séparé est seul
  autorisé à gérer le cycle de vie des utilisateurs en V1 ;
- un utilisateur Keycloak est désactivé plutôt que supprimé par défaut ;
- une commande idempotente `deprovision_remote_access` supprime les credentials
  SSO et liaisons Warpgate, puis vérifie qu'aucun credential ne porte encore
  l'email ; elle échoue sans autoriser la suite si Warpgate est indisponible ;
- le compte break-glass ne peut supprimer un utilisateur ou réattribuer son
  email qu'après le succès de cette commande ;
- avant de supprimer un utilisateur Django, supprimer ses services et données
  afin d'éviter des workloads Kubernetes orphelins ;
- après un changement administratif d'email, révoquer les sessions Keycloak,
  demander une nouvelle connexion Ilosia, puis exécuter Restart ou Reconcile ;
- documenter chaque déprovisionnement dans le runbook opérateur.

Le backend OIDC existant met déjà à jour l'email Django depuis le claim à
chaque connexion. AW5 conserve un test de non-régression sur ce comportement,
car les `ensure_sso_credential` utilisent cet email synchronisé.

Une évolution pourra remplacer l'email réel par un attribut OIDC Warpgate
stable, unique et immuable. Ce changement n'est pas nécessaire pour la V1 tant
que la non-réutilisation est imposée par les permissions Keycloak, la commande
de déprovisionnement et la garde applicative décrite ci-dessous.

### Client OIDC Warpgate

Créer un second client dans le realm `ilosia` :

```text
clientId: warpgate
type: confidential
standardFlowEnabled: true
directAccessGrantsEnabled: false
clientSecret: <injecté depuis WARPGATE_OIDC_CLIENT_SECRET>
```

Redirect URI :

```text
https://access.ilosia.example/@warpgate/api/sso/return
```

Back-channel logout :

```text
https://access.ilosia.example/@warpgate/api/sso/providers/keycloak/backchannel-logout
```

AW0 avec Warpgate 0.30.2 confirme que ce back-channel est accepté mais ne coupe
pas un canal SSH déjà approuvé. Il invalide bien la session web OIDC : une
nouvelle connexion SSH exige une nouvelle authentification Keycloak puis une
nouvelle approbation Warpgate. Le logout volontaire conserve donc la connexion
SSH en cours. En revanche, un désabonnement ou une
désactivation administrative doit passer par le déprovisionnement Ilosia, qui
révoque la liaison de rôle Warpgate afin de fermer les sessions actives ; ce
comportement est testé en AW5. Désactiver seulement le compte dans Keycloak
n'est pas une procédure de révocation immédiate des sessions SSH existantes.

Scopes et claims nécessaires :

```text
openid
profile
email
sub
preferred_username
email_verified
```

Le claim `groups` est inutile pour ce client.

Le secret du client est stocké dans le Secret Kubernetes de Warpgate, jamais
dans le ConfigMap du realm ni dans Git.

Warpgate exige un email vérifié lorsque le fournisseur OIDC publie ce statut.
Keycloak bloque en plus la connexion tant que `VERIFY_EMAIL` n'est pas
satisfaite, et Django vérifie le claim `email_verified` lorsqu'il ouvre sa
propre session.

### Application de la configuration Keycloak

`start --import-realm` initialise uniquement une base vide et n'écrase pas le
realm `ilosia` existant. AW1 ajoute donc un script idempotent
`scripts/configure_keycloak_warpgate.sh` utilisant `kcadm` ou l'Admin API pour :

1. appliquer les règles d'email du realm ;
2. créer ou mettre à jour le client confidentiel `warpgate` ;
3. configurer les redirect et back-channel logout URIs ;
4. configurer les scopes et claims ;
5. vérifier qu'aucun compte Ilosia ordinaire ne reçoit les rôles
   `realm-management` ;
6. conserver l'administration des utilisateurs sur un compte break-glass
   séparé ;
7. relire l'état obtenu et échouer s'il diverge.

Le script est exécuté deux fois dans le test AW1 pour vérifier son idempotence.
En production, il met à jour le realm ; il ne supprime ni ne recrée la base
Keycloak.

## 10. Modèle d'autorisation Warpgate

Pour un utilisateur :

```text
Keycloak user
    |
    v
Warpgate user u-42
    |
    v
Warpgate role ilosia-user-42
    |
    +--> target aw-<workspace A>
    +--> target aw-<workspace B>
```

`auto_create_users` est désactivé. Ilosia assure explicitement :

```text
ensure_user(name="u-42")
ensure_sso_credential(user="u-42", provider="keycloak", email=<verified email>)
ensure_role(name="ilosia-user-42")
ensure_user_role(user="u-42", role="ilosia-user-42")
ensure_ssh_target(
    name="aw-...",
    host=<service DNS>,
    port=2222,
    username="developer",
    authentication="public-key",
    client_keys="default",
)
ensure_target_role(target="aw-...", role="ilosia-user-42")
```

Les méthodes retrouvent les objets par nom et convergent vers l'état désiré.
Elles ne créent pas de doublons et corrigent les champs modifiés, notamment
l'email du credential SSO.

Avant toute création ou mise à jour, `ensure_sso_credential` recherche le
couple fournisseur/email dans tous les credentials Warpgate. Si l'email est
déjà rattaché à un autre utilisateur `u-*`, il échoue avant Helm et journalise
une collision d'identité sans déplacer le credential. Une collision reçue
pendant une création concurrente est relue puis soumise à la même règle.

Cette garde protège le provisioning mais pas une connexion directe à Warpgate.
La restriction des permissions Keycloak et `deprovision_remote_access` restent
donc obligatoires avant toute réutilisation d'adresse.

Les créations concurrentes sont normales : si un `ensure_*`, notamment
`ensure_user`, reçoit un conflit de création, il relit l'objet par son nom puis
poursuit la convergence au lieu d'échouer.

AW1 configure aussi la politique d'authentification globale des utilisateurs
ordinaires :

- HTTP accepte uniquement le SSO Keycloak ;
- SSH utilise l'authentification navigateur out-of-band ;
- les mots de passe SSH sont désactivés ;
- l'auto-création des utilisateurs reste désactivée ;
- l'ajout autonome de mots de passe, clés publiques et API tokens est désactivé ;
- seul le compte technique Ilosia conserve un API token avec des permissions
  administratives minimales.

La première connexion à une target demande de confirmer sa clé hôte. La target
et les clés hôte du workspace étant persistantes, cette confirmation ne doit
pas réapparaître après Stop/Restart.

Un compte API Warpgate dédié à Ilosia possède uniquement les permissions
nécessaires pour gérer utilisateurs, credentials SSO, rôles, targets et
liaisons. Son token est stocké dans `ilosia-secrets`, jamais en base ou dans les
values GitOps.

Les appels à l'API d'administration utilisent HTTPS. En production, le
certificat est signé par l'autorité exposée par l'ingress. En développement,
Ilosia charge explicitement la CA du certificat auto-signé via
`WARPGATE_CA_BUNDLE`. La vérification TLS n'est jamais désactivée.

## 11. Connexion Herdr et approbation navigateur

Herdr utilise OpenSSH. Sur Linux et macOS, il gère déjà un socket de contrôle
privé par attachement lorsque `remote.manage_ssh_config=true`.

AW0 teste d'abord le comportement par défaut. Ne pas ajouter immédiatement un
`ControlMaster` Ilosia susceptible d'entrer en conflit avec Herdr.

Ordre des parades si plusieurs approbations navigateur apparaissent :

1. conserver la réutilisation SSH native de Herdr ;
2. configurer le cache d'approbation Warpgate ;
3. tester ensuite un `ControlPersist` explicite ;
4. ne pas utiliser une clé publique utilisateur comme alternative au SSO, car
   elle contournerait la révocation Keycloak.

La page de connexion indique la version serveur Herdr et une version client
minimale testée. AW0 teste au moins client N/serveur N, client N-1/serveur N et
client N/serveur N-1.

## 12. Déploiement Warpgate

Warpgate est une application système séparée :

```text
gitops/applications/warpgate.yaml
gitops/dev/warpgate-values.yaml
```

### Développement

- une réplique ;
- SQLite sur PVC ;
- interface web via NGINX Ingress ;
- Service SSH de type `LoadBalancer` ;
- port hôte k3d `2222` mappé vers le load balancer ;
- enregistrements complets de session désactivés ;
- image et chart épinglés à une version exacte de Warpgate `>= 0.30`, nécessaire
  au back-channel logout.

Le PVC Warpgate contient SQLite et les clés SSH client générées par Warpgate.
Ces clés sont stockées dans la base, pas dans des fichiers indépendants. AW1
effectue une sauvegarde SQLite cohérente avec la commande `.backup`, conserve
la version Warpgate et protège la sauvegarde comme un secret. Une copie à chaud
du seul fichier SQLite ou du PVC n'est pas considérée comme une sauvegarde.

Le Secret Warpgate contient au minimum :

```text
WARPGATE_ADMIN_PASSWORD
WARPGATE_OIDC_CLIENT_SECRET
WARPGATE_ENCRYPTION_KEY
```

La clé de chiffrement est générée une fois, sauvegardée séparément et restaurée
avec la base. La restauration complète est testée dans AW1.

Extrait k3d :

```yaml
ports:
  - port: 8080:80
    nodeFilters:
      - loadbalancer
  - port: 2222:2222
    nodeFilters:
      - loadbalancer
```

AW0 doit confirmer que le mapping et le Service `LoadBalancer` suffisent sans
`kubectl port-forward`.

### Production ultérieure

Warpgate supporte officiellement plusieurs nœuds avec PostgreSQL ou MySQL
partagé et communication inter-nœuds. La V1 reste néanmoins mono-réplique. Le HA
ne sera activé qu'après un test dédié de sessions SSH pendant la perte d'un Pod.

L'opérateur Kubernetes Warpgate n'est pas utilisé. Ilosia appelle directement
l'API Warpgate.

## 13. Clé technique Warpgate

Warpgate possède une clé privée dédiée pour les connexions aux workspaces. Sa
partie publique est transmise au chart :

```yaml
warpgate:
  publicKeys:
    - ssh-ed25519 AAAA...
```

La clé privée reste exclusivement dans Warpgate. Les clés publiques communes
proviennent de la configuration Ilosia et sont passées aux values de chaque
release. Aucun Secret `authorized_keys` propre au workspace n'est créé.

En V1, `WARPGATE_PUBLIC_KEYS` est recopié manuellement depuis la clé publique
client de Warpgate après AW1, puis après toute recréation du PVC Warpgate. La
lecture automatique depuis l'API d'administration sera évaluée ultérieurement
si la version épinglée l'expose ; elle n'est pas retenue maintenant afin de
conserver un chevauchement contrôlé pendant les rotations.

La clé privée générée par Warpgate vit dans sa base SQLite sur le PVC. Perdre
cette base change la clé. Il faut alors recopier sa nouvelle partie publique
dans `WARPGATE_PUBLIC_KEYS`, puis exécuter Restart ou un Helm upgrade des
workspaces avant qu'ils redeviennent joignables. Une injection par Secret ne
sera ajoutée que si le chart et la version Warpgate épinglés l'acceptent
officiellement.

### Rotation planifiée

1. ajouter la nouvelle clé publique ;
2. laisser les sessions actives continuer ;
3. appliquer la nouvelle configuration au prochain Stop/Restart ;
4. mettre à jour progressivement les workspaces actifs si nécessaire ;
5. retirer l'ancienne clé après convergence.

### Clé compromise

1. ajouter immédiatement une nouvelle clé ;
2. exécuter un Helm upgrade de tous les workspaces actifs ;
3. prévenir que la stratégie `Recreate` tue les sessions Herdr et Codex ;
4. vérifier la reconnexion ;
5. retirer l'ancienne clé.

## 14. Image Agent Workspace

Nouvelle image indépendante :

```text
ghcr.io/quaxsze/ilosia-agent-workspace:<commit-sha>
```

Elle est publiée en architectures `linux/amd64` et `linux/arm64`.

### Contenu de base

```text
OpenSSH server
Git
curl
jq
ripgrep
make
gcc/g++
pkg-config
Python
Node.js LTS
uv
mise
Herdr épinglé
Codex CLI épinglé
certificats TLS
```

Il s'agit d'une image de développement non-root, pas d'une image minimale.

Elle ne contient pas :

- Docker ;
- `kubectl` ;
- Helm ;
- credential ;
- clé privée Warpgate ;
- token de ServiceAccount.

### Utilisateur et filesystem

```text
user: developer
uid: 1000
gid: 1000
HOME: /workspace/home
working directory: /workspace/repository
```

Le PVC est monté sur `/workspace` :

```text
/workspace/
├── home/
│   ├── .cache/
│   ├── .config/
│   ├── .local/
│   └── .local/share/mise/
├── repository/
└── ssh-host-keys/
```

Les installations utilisateur faites par `mise`, `uv` ou npm restent sur le
PVC. Les clés hôte SSH restent également sur le PVC afin de conserver la même
identité après Restart.

Au premier démarrage, si `$HOME/.gitconfig` ne définit pas encore d'identité,
l'entrypoint initialise :

```text
user.name  = nom complet Django, sinon username
user.email = email Keycloak vérifié
```

Ces valeurs non secrètes sont dérivées côté serveur et transmises aux values
Helm. L'entrypoint ne remplace jamais une configuration ensuite modifiée par
l'utilisateur.

Un dépôt nécessitant une bibliothèque système absente devra attendre une image
spécialisée ultérieure ; `apt install` n'est pas disponible à l'exécution.

## 15. Authentification et sandbox Codex

Keycloak n'authentifie pas Codex.

La méthode recommandée dans un workspace distant est :

```bash
codex login --device-auth
```

Alternative :

```bash
printenv OPENAI_API_KEY | codex login --with-api-key
```

Django ne collecte ni ne stocke les credentials OpenAI. La documentation doit
expliquer que le login OAuth loopback standard vise le localhost de la machine
distante et n'est pas adapté quand le port forwarding est désactivé.

Le Pod Kubernetes est la frontière principale de sécurité.

AW0 tente d'abord :

```bash
codex --sandbox workspace-write --ask-for-approval on-request
```

Si le sandbox interne ne fonctionne pas sous PSS restricted :

```bash
codex --sandbox danger-full-access --ask-for-approval on-request
```

Dans ce mode, `danger-full-access` signifie accès complet à l'intérieur du Pod,
pas au nœud ou au cluster. Ne pas utiliser par défaut
`--dangerously-bypass-approvals-and-sandbox`.

Tout credential injecté dans le workspace est considéré lisible par Codex et
par le code du dépôt.

## 16. Chart `agent-workspace`

```text
charts/agent-workspace/
├── Chart.yaml
├── values.yaml
└── templates/
    ├── deployment.yaml
    ├── service.yaml
    ├── pvc.yaml
    └── networkpolicy.yaml
```

Ressources :

- Deployment à une réplique, stratégie `Recreate` ;
- Service `ClusterIP` sur TCP 2222 ;
- PVC `ReadWriteOnce` avec `helm.sh/resource-policy: keep` ;
- NetworkPolicy ingress et egress ;
- readiness et liveness probes TCP sur 2222 ;
- volumes temporaires bornés pour `/tmp` et `/run`.

Le chart n'ajoute pas de ConfigMap si la configuration SSH peut être incluse
dans l'image et paramétrée par arguments ou variables. Le ClusterRole actuel
`ilosia-user-workload` couvre déjà Deployment, Service, PVC, Secret et
NetworkPolicy ; aucune modification RBAC n'est prévue.

### Sécurité du Pod

```yaml
automountServiceAccountToken: false

securityContext:
  runAsNonRoot: true
  runAsUser: 1000
  runAsGroup: 1000
  fsGroup: 1000
  seccompProfile:
    type: RuntimeDefault
```

```yaml
securityContext:
  allowPrivilegeEscalation: false
  readOnlyRootFilesystem: true
  capabilities:
    drop: [ALL]
```

Écritures autorisées uniquement dans `/workspace`, `/tmp` et `/run`.

Le root filesystem restant en lecture seule, le Pod monte :

```yaml
volumes:
  - name: tmp
    emptyDir:
      sizeLimit: 1Gi
  - name: run
    emptyDir:
      medium: Memory
      sizeLimit: 64Mi
```

Le conteneur déclare par défaut :

```yaml
resources:
  requests:
    ephemeral-storage: 256Mi
  limits:
    ephemeral-storage: 2Gi
```

Ces valeurs sont configurables dans le chart. Elles bornent chaque Agent
Workspace sans modifier le `ResourceQuota` utilisateur ni le comportement
actuel de `ensure_namespace`. Le quota existant continue de gérer CPU, mémoire,
PVC et nombre de Pods ; Jupyter reste inchangé.

La readiness probe empêche Helm et le statut Kubernetes de considérer le Pod
prêt tant que sshd n'écoute pas réellement sur 2222.

### Configuration SSH

- écoute sur 2222 ;
- utilisateur `developer` uniquement ;
- mot de passe interdit ;
- login root interdit ;
- clés publiques Warpgate uniquement ;
- X11, tunnel et agent forwarding désactivés en V1 ;
- clés hôte persistées sur le PVC.

## 17. Réseau Kubernetes

### Ingress du workspace

Autoriser uniquement Warpgate vers TCP 2222 :

```yaml
ingress:
  - from:
      - namespaceSelector:
          matchLabels:
            kubernetes.io/metadata.name: warpgate
        podSelector:
          matchLabels:
            app.kubernetes.io/name: warpgate
    ports:
      - protocol: TCP
        port: 2222
```

Le label `app.kubernetes.io/name: warpgate` doit être vérifié sur les Pods du
chart Warpgate épinglé, comme le label CoreDNS ci-dessous.

### DNS

Autoriser explicitement CoreDNS :

```yaml
egress:
  - to:
      - namespaceSelector:
          matchLabels:
            kubernetes.io/metadata.name: kube-system
        podSelector:
          matchLabels:
            k8s-app: kube-dns
    ports:
      - protocol: UDP
        port: 53
      - protocol: TCP
        port: 53
```

Le label CoreDNS réel doit être vérifié sur k3d et Scaleway.

### Egress public

```yaml
  - to:
      - ipBlock:
          cidr: 0.0.0.0/0
          except:
            - 10.0.0.0/8
            - 100.64.0.0/10
            - 169.254.0.0/16
            - 172.16.0.0/12
            - 192.168.0.0/16
      - ipBlock:
          cidr: ::/0
          except:
            - fc00::/7
            - fe80::/10
    ports:
      - protocol: TCP
        port: 443
```

La V1 autorise uniquement HTTPS vers Internet. AW0 vérifie que GitHub, OpenAI
et les gestionnaires de toolchains retenus fonctionnent sans TCP 80. Si un cas
supporté exige réellement HTTP, le port 80 sera ajouté explicitement après ce
test, pas ouvert par défaut.

Le chart accepte en plus une liste propre à l'environnement :

```yaml
networkPolicy:
  blockedCidrs:
    - <control-plane-public-ip>/32
    - <control-plane-public-ipv6>/128
```

Ces CIDR sont ajoutés aux entrées `except`. Pour Scaleway, ils sont dérivés de
l'`api_server_url` Terraform et conservés dans les values GitOps.

La V1 ne modifie pas l'ACL du control plane : bloquer sans preuve les IP de
sortie des workers pourrait couper les kubelets, Django ou Helm de l'API. Une
ACL plus restrictive reste un durcissement optionnel après AW0 seulement si un
test démontre le chemin privé des workers et conserve simultanément :

- tous les nœuds `Ready` ;
- les appels Kubernetes de Django ;
- Launch, Stop et Restart via Helm ;
- les opérations de maintenance et de mise à niveau du cluster.

Cela doit bloquer :

- réseaux privés Kubernetes ;
- IP des nœuds ;
- API Kubernetes par ClusterIP ou IP de nœud ;
- Carrier-Grade NAT ;
- Metadata API Scaleway `169.254.42.42` ;
- services link-local ;
- réseaux IPv6 privés et link-local.

Le comportement après DNAT dépend du CNI. Les tests réels sur k3d puis Scaleway
sont des critères bloquants de sécurité. Sur Scaleway, le test vise aussi
l'`api_server_url` et son port réels lus dans le kubeconfig, sans supposer 443
ou 6443. Un changement d'adresse du control plane impose la mise à jour des
values GitOps avant déploiement.

La NetworkPolicy Jupyter existante ne change pas. Elle interdit déjà l'entrée
depuis le workspace dans le même namespace.

## 18. Calcul du statut

`_pods_status` doit analyser :

```text
status.initContainerStatuses
status.containerStatuses
```

Un init container entraîne `FAILED` s'il :

- termine avec un code non nul ;
- attend avec `CrashLoopBackOff` ;
- rencontre `CreateContainerConfigError` ;
- rencontre `ErrImagePull` ou `ImagePullBackOff`.

Un init container encore actif correspond à `INSTALLING`.

Le rafraîchissement HTMX, exécuté toutes les cinq secondes, interroge uniquement
Kubernetes. Il ne contacte jamais Warpgate. Les `ensure_*` de Launch et Restart
établissent l'état Warpgate ; le réconciliateur corrige ensuite les écarts hors
du chemin de rafraîchissement.

Dans `refresh_service_status` :

- si Kubernetes est temporairement indisponible, rendre `UNKNOWN` pour la
  réponse courante en modifiant seulement l'instance en mémoire, sans
  l'enregistrer en base ; le prochain poll repart du dernier état persistant
  connu ;
- si le statut persistant est déjà `UNKNOWN`, le conserver jusqu'à une action
  Stop ou Restart, sans le promouvoir automatiquement depuis les Pods ;
- si le statut persistant est `FAILED` et qu'aucun Pod n'existe, conserver
  `FAILED` au lieu de passer à `UNKNOWN`.

Ainsi, l'échec d'un rollback ne peut pas devenir un faux `RUNNING`, une panne
passagère de l'API Kubernetes se résorbe au poll suivant, et un Pod en erreur
passagère peut repasser normalement de `FAILED` à `RUNNING` lorsqu'il redevient
prêt.

Le nom du conteneur de logs doit devenir un paramètre :

```text
jupyter        → jupyter
agent-workspace → workspace
```

## 19. Cycle de vie

### Launch

Valider `repository_url`, puis réutiliser sans le réécrire le bloc transactionnel
existant :

```text
transaction.atomic
→ select_for_update(user)
→ compter les services non DELETED
→ appliquer MAX_SERVICES_PER_USER
→ créer ServiceInstance(INSTALLING)
→ terminer la transaction
```

Tous les appels Warpgate, Kubernetes et Helm s'exécutent ensuite hors de cette
transaction et donc hors du verrou utilisateur :

```text
1. ensure user Warpgate
2. ensure credential SSO avec l'email vérifié courant
3. ensure rôle
4. ensure liaison user → rôle
5. ensure namespace avec le ResourceQuota existant, sans nouvelle règle de quota
6. Helm upgrade --install agent-workspace
7. ensure target vers le DNS du Service
8. ensure liaison target → rôle
9. RUNNING
```

Toute erreur avant Helm, notamment Warpgate, namespace ou quota : aucun
workload, statut `FAILED`.

À partir du premier appel Helm, toute erreur de Helm ou Warpgate applique la
même règle de rollback :

```text
helm uninstall --ignore-not-found réussi
→ conserver le PVC
→ FAILED

helm uninstall échoué
→ journaliser l'erreur initiale et l'erreur de cleanup
→ UNKNOWN
```

Cette règle couvre aussi un échec du rollback interne de `--atomic`. Un service
ne passe à `RUNNING` qu'après réussite de Helm, de la target et de sa liaison au
rôle. Après `FAILED` ou `UNKNOWN`, Restart répare l'ensemble.

### Stop

Autorisé pour `RUNNING` et `UNKNOWN` :

```text
STOPPING
→ helm uninstall
→ STOPPED
```

Aucun appel Warpgate. La target reste présente mais ne mène à aucun Service.

### Restart

Autorisé pour `STOPPED`, `FAILED` et `UNKNOWN` :

```text
1. INSTALLING
2. helm uninstall --ignore-not-found
3. si uninstall échoue : UNKNOWN et arrêt
4. ensure user Warpgate
5. ensure credential SSO avec l'email courant
6. ensure rôle
7. ensure liaison user → rôle
8. Helm upgrade --install avec le même release et PVC
9. ensure target avec le DNS stable
10. ensure liaison target → rôle
11. RUNNING
```

Restart détruit donc toujours le Pod éventuellement restant, mais conserve le
PVC. Il répare une target, un rôle, une liaison ou un credential absent ou
désynchronisé. Toute erreur après l'étape Helm réutilise la règle de rollback du
Launch ; une erreur Warpgate avant Helm produit `FAILED` puisqu'aucun workload
n'existe alors.

### Delete service and data

```text
1. DELETING
2. helm uninstall
3. si uninstall échoue : UNKNOWN et arrêt sans supprimer les données
4. supprimer la target Warpgate par son nom
5. supprimer le PVC
6. si la suppression du PVC échoue : UNKNOWN
7. DELETED
```

Une panne Warpgate est journalisée mais n'empêche ni la suppression du PVC ni
le passage à `DELETED`. Une target orpheline ne mène plus à rien et sera
supprimée par le réconciliateur. En revanche, un échec Helm ou Kubernetes
interrompt la suppression pour ne pas déclarer les données détruites à tort.

## 20. Réconciliation

Ajouter une commande idempotente :

```bash
python manage.py reconcile_agent_workspaces
```

Elle :

1. liste les `ServiceInstance` Agent Workspace non supprimés ;
2. ensure les users, credentials, rôles et liaisons utilisateurs ;
3. ensure les targets et liaisons pour les services actifs ou arrêtés ;
4. vérifie que chaque target utilise le DNS stable attendu ;
5. supprime toute target `aw-*` sans ServiceInstance non `DELETED` correspondant ;
6. ne démarre et n'arrête aucun workload ;
7. produit des logs structurés.

La V1 peut exécuter la commande manuellement. Une CronJob ne sera ajoutée que
si le besoin opérationnel est confirmé.

### Déprovisionnement d'une identité distante

Après désactivation du compte Keycloak et suppression de tous ses services,
l'opérateur exécute :

```bash
python manage.py deprovision_remote_access --user-id <django-user-id>
```

La commande :

1. refuse d'agir tant qu'un `ServiceInstance` non `DELETED` appartient au
   compte ;
2. supprime les éventuelles targets résiduelles de ses services, les credentials
   SSO, liaisons de rôles, rôle et utilisateur Warpgate déterministes ;
3. relit tous les credentials du fournisseur Keycloak et vérifie que l'email
   n'apparaît plus ;
4. journalise l'opération sans l'email en clair ;
5. retourne un code non nul au moindre échec ou état résiduel.

La suppression du compte Keycloak ou la réattribution de son email n'est une
opération supportée qu'après le succès de cette commande. `auto_create_users`
restant désactivé, l'ancien compte ne peut plus être recréé par une connexion
SSO.

## 21. Changements applicatifs

### Nouveaux fichiers prévus

```text
workloads/agent_workspace_services.py
infrastructure/warpgate_client.py
charts/agent-workspace/Chart.yaml
charts/agent-workspace/values.yaml
charts/agent-workspace/templates/deployment.yaml
charts/agent-workspace/templates/service.yaml
charts/agent-workspace/templates/pvc.yaml
charts/agent-workspace/templates/networkpolicy.yaml
images/agent-workspace/Dockerfile
workloads/templates/workloads/components/agent_workspace_access.html
workloads/management/commands/reconcile_agent_workspaces.py
workloads/management/commands/deprovision_remote_access.py
gitops/applications/warpgate.yaml
gitops/dev/warpgate-values.yaml
scripts/configure_keycloak_warpgate.sh
scripts/check_agent_workspace.sh
```

### Fichiers modifiés prévus

```text
catalog/migrations/
workloads/models.py
workloads/migrations/
workloads/forms.py
workloads/services.py
workloads/views.py
workloads/templates/workloads/launch.html
workloads/templates/workloads/detail.html
workloads/templates/workloads/components/status.html
workloads/tests.py
infrastructure/exceptions.py
infrastructure/kubernetes_client.py
infrastructure/tests.py
config/settings.py
charts/ilosia/templates/keycloak.yaml
charts/ilosia/values.yaml
gitops/dev/values.yaml
k8s/bootstrap/k3d.yaml
.github/workflows/ci.yml
.github/workflows/publish.yml
README.md
```

`charts/ilosia/templates/rbac.yaml` n'a pas besoin d'être modifié avec les
ressources prévues.

### Dispatch explicite

`workloads/services.py` conserve les points d'entrée actuels et délègue selon
le slug :

```text
jupyter         → logique existante
agent-workspace → agent_workspace_services.py
```

Réglages explicites :

```python
JUPYTER_CHART_PATH = BASE_DIR / "charts" / "jupyter"
AGENT_WORKSPACE_CHART_PATH = BASE_DIR / "charts" / "agent-workspace"

WARPGATE_URL = "https://warpgate..."
WARPGATE_API_TOKEN = "..."
WARPGATE_CA_BUNDLE = "/etc/ilosia/warpgate-ca/ca.crt"
WARPGATE_PUBLIC_KEYS = ["ssh-ed25519 AAAA..."]
```

Ces réglages sont déclarés dans `config/settings.py` et exposés par les values
du chart Ilosia. `WARPGATE_API_TOKEN` provient d'un Secret Kubernetes ; la CA
est montée en lecture seule ; les clés publiques ne sont pas secrètes. Le
client utilise `WARPGATE_CA_BUNDLE` pour vérifier le certificat auto-signé de
développement et le trust store système quand ce réglage est vide en
production.

Le Secret du déploiement Warpgate, distinct des réglages Django, fournit
`WARPGATE_OIDC_CLIENT_SECRET` et `WARPGATE_ENCRYPTION_KEY` au chart Warpgate.

## 22. Observabilité

Réutiliser les compteurs existants sans leur ajouter de label :

```text
ilosia_service_launch_total
ilosia_service_launch_failed_total
ilosia_service_delete_total
```

La branche Agent Workspace incrémente les mêmes compteurs aux mêmes moments que
Jupyter.

Logs structurés minimaux :

```text
service_slug
service_id
user_id
release_name
warpgate_target_name
operation
result
```

Ilosia journalise Launch, Stop, Restart, Delete et Reconcile. Warpgate conserve
ses propres événements de connexion. Aucun modèle `AuditEvent` n'est créé en
V1.

Les enregistrements complets des terminaux sont désactivés : ils peuvent
contenir code privé, prompts, résultats de commandes et credentials.

## 23. Sécurité

Chaque endpoint charge le service avec :

```python
get_object_or_404(ServiceInstance, id=service_id, user=request.user)
```

Le navigateur ne fournit jamais :

- namespace ;
- release name ;
- target Warpgate ;
- rôle Warpgate ;
- chart path ;
- host SSH interne.

Le Pod :

- n'a aucun token Kubernetes ;
- ne monte aucune socket privilégiée ;
- tourne non-root ;
- applique seccomp `RuntimeDefault` ;
- supprime toutes ses capabilities ;
- n'accède qu'à son PVC ;
- ne peut recevoir du trafic que de Warpgate ;
- ne peut atteindre ni les réseaux privés ni les metadata cloud ;
- peut atteindre Internet en HTTPS et kube-dns.

Le Pod constitue le sandbox de sécurité principal. Codex peut lire tous les
fichiers et credentials présents dans ce Pod.

## 24. AW0 — spike technique bloquant

AW0 ne modifie pas Django. Il utilise des ressources et commandes temporaires
uniquement pour trancher les inconnues capables d'invalider l'architecture.
Les tests de configuration et de cycle de vie restent dans leurs milestones
d'implémentation respectifs.

Le développement local passe par une seule entrée idempotente,
`scripts/setup_agent_workspace_aw0.sh`. Elle vérifie les prérequis, converge
Warpgate et le workspace, récupère les clés client SSH, puis ensure la target,
le rôle et les liaisons. Le token API Warpgate est créé une fois dans l'UI et
conservé uniquement dans un Secret du cluster local. Une relance sans changement
ne redémarre pas le workspace. AW1 et AW2 remplaceront les ressources du spike
par les charts définitifs sans réintroduire une procédure manuelle multi-étapes.

### 24.1 Connexions SSH Herdr

Mesurer dans les logs Warpgate :

| Action | Mesure |
|---|---|
| `herdr machine add` | connexions SSH et approbations navigateur |
| premier `herdr --remote` | connexions et approbations |
| detach/reattach | réutilisation de la connexion |
| coupure réseau | comportement de reconnexion |
| expiration de session web | nouvelle approbation |
| client N / serveur N | compatibilité |
| client N-1 / serveur N | compatibilité |
| client N / serveur N-1 | compatibilité |

Critère : au maximum une approbation navigateur par utilisateur/cible pendant
la période de cache retenue.

### 24.2 Authentification Codex

Tester :

```bash
codex login --device-auth
codex login status
```

Puis :

1. détacher Herdr ;
2. se reconnecter ;
3. redémarrer le Pod avec le même PVC ;
4. vérifier l'état d'authentification ou documenter la réauthentification.

### 24.3 Sandbox Codex

Sous PSS restricted, tester :

- lecture et écriture du dépôt ;
- `git diff` et `git commit` ;
- lancement de tests ;
- accès réseau autorisé.

Tester d'abord `workspace-write`. Si le sandbox interne échoue, tester
`danger-full-access` avec approbations `on-request` et confirmer que le Pod reste
la frontière effective. Le refus des chemins hors PVC est testé uniquement avec
`workspace-write` : il n'est pas attendu avec `danger-full-access`.

### 24.4 Temps de premier lancement

Mesurer séparément et ensemble :

| Scénario | Mesure |
|---|---|
| image en cache + petit dépôt | référence |
| image froide + petit dépôt | coût de l'image |
| image en cache + gros dépôt | coût du clone |
| image froide + gros dépôt | pire cas |
| dépôt invalide | délai avant `FAILED` |
| deux lancements froids simultanés | disponibilité de l'interface |

Le pire cas officiellement supporté doit finir ou échouer avant le timeout Helm
d'environ cinq minutes et le timeout Gunicorn de 360 secondes. Pendant deux
lancements simultanés, `/healthz`, le login et le rafraîchissement de statut
doivent rester disponibles sans attendre la fin des installations.

Si le délai ou le test de concurrence échoue, le résultat d'AW0 est :
**provisionnement asynchrone obligatoire avant intégration Django**. Augmenter
seulement les timeouts ou le nombre de workers n'est pas une solution. AW3 reste
bloqué jusqu'à la définition et au test du worker de provisioning.

### 24.5 Egress

Depuis le Pod :

```text
github.com                 → autorisé
api.openai.com             → autorisé
TCP 80 public              → refusé
kubernetes.default.svc     → refusé
KUBERNETES_SERVICE_HOST    → refusé
IP d'un nœud sur 6443      → refusé
api_server_url, port réel  → refusé
169.254.42.42              → refusé
169.254.169.254            → refusé
```

Tester aussi les installations utilisateur prévues par AW2 afin de décider si
TCP 443 suffit. Répéter les refus sensibles sur k3d et Scaleway. AW0 échoue si
l'API Kubernetes, y compris son endpoint public réel, ou les metadata restent
accessibles.

Une éventuelle restriction de l'ACL du control plane est testée séparément et
annulée au moindre impact sur les nœuds, Django, Helm ou la maintenance. Elle
n'est pas requise pour la décision Go de la V1 si la NetworkPolicy bloque déjà
le workspace.

### 24.6 Logout Keycloak

Tester le logout Keycloak et documenter s'il ferme immédiatement la session
Warpgate ou seulement les nouvelles authentifications. AW0 a observé que
Warpgate 0.30.2 accepte le token, invalide la session web OIDC, mais laisse le
canal SSH déjà approuvé ouvert. Une nouvelle connexion exige bien une nouvelle
authentification Keycloak et une nouvelle approbation Warpgate. La fermeture
immédiate lors d'un
déprovisionnement repose sur la révocation de rôle Warpgate et relève des tests
de sécurité AW5.

### 24.7 Sortie d'AW0

AW0 produit un compte rendu avec :

- versions exactes Herdr, Codex et Warpgate testées ;
- nombre de connexions SSH et d'approbations ;
- mode sandbox Codex retenu ;
- temps de lancement mesurés ;
- résultat de deux lancements froids simultanés et disponibilité du web ;
- résultats egress k3d et Scaleway ;
- décision documentée de laisser l'ACL inchangée ou preuve autorisant son
  durcissement ultérieur ;
- décision sur TCP 443 seul ou ajout justifié de TCP 80 ;
- comportement du logout ;
- décision synchrone ou asynchrone ;
- décision Go/No-Go pour AW1.

## 25. Ordre d'implémentation

### AW0 — Spike technique

Valider tous les critères de la section 24. Aucun code Django Agent Workspace.

### AW1 — Warpgate système

- chart externe et Warpgate `>= 0.30` épinglés à des versions exactes ;
- application Argo CD ;
- values dev ;
- PVC SQLite ;
- Service LoadBalancer SSH ;
- Ingress web ;
- client Keycloak ;
- back-channel logout ;
- script idempotent de mise à jour du realm existant ;
- aucun rôle `realm-management` sur les comptes Ilosia ordinaires ;
- secret OIDC Warpgate ;
- compte API Ilosia ;
- validation des endpoints CRUD de l'API d'administration sur la version
  épinglée ;
- politique HTTP SSO-only et SSH in-browser auth ;
- gestion autonome des credentials désactivée pour les utilisateurs ;
- CA de l'API d'administration ;
- configuration de la clé technique ;
- chiffrement des credentials au repos ;
- sauvegarde SQLite cohérente et restauration complète ;
- tests manuels OIDC et SSH.

### AW2 — Image et chart Agent Workspace

- image multiarchitecture ;
- utilisateur non-root ;
- sshd sur 2222 ;
- Herdr et Codex épinglés ;
- toolchains et installations utilisateur sur le PVC ;
- PVC ;
- identité Git initialisée sans écraser les choix utilisateur ;
- `/tmp` et `/run` montés et bornés ;
- limites de stockage éphémère ;
- probes TCP sur 2222 ;
- clone idempotent et erreurs d'init container ;
- Service DNS stable ;
- NetworkPolicy ;
- tests Helm.

### AW3 — Intégration Django

- migration `repository_url` ;
- seed catalogue ;
- formulaire spécialisé ;
- validation GitHub ;
- chemins de charts séparés ;
- préfixes de release ;
- `WarpgateClient` ;
- détection fail-closed des collisions d'email Warpgate ;
- Launch avec verrou et quota existants ;
- rollback uniforme après toute erreur pouvant laisser une release ;
- page de détail et instructions ;
- récupération des logs ;
- tests unitaires.

### AW4 — Cycle de vie et réparation

- Stop sans Warpgate ;
- Restart depuis STOPPED, FAILED et UNKNOWN, précédé d'un uninstall, avec tous
  les `ensure_*` ;
- Delete et suppression de target ;
- statut rafraîchi depuis Kubernetes uniquement ;
- actions UI alignées sur chaque statut et chaque slug, sans étendre Restart
  pour Jupyter ;
- commande de réconciliation ;
- tests de panne et idempotence du `WarpgateClient` ;
- test DNS stable malgré un changement de ClusterIP ;
- persistance du dépôt, du commit et de la clé hôte après Stop/Restart.

### AW5 — E2E, observabilité et sécurité

- script E2E ;
- tests d'isolation croisée ;
- tests egress ;
- tests Keycloak : email vérifié, email unique et email non modifiable ;
- absence de rôle d'administration Keycloak sur les comptes Ilosia ordinaires ;
- garde de collision email dans `ensure_sso_credential` ;
- commande fail-closed `deprovision_remote_access` ;
- resynchronisation du credential après changement administratif d'email ;
- déprovisionnement avant suppression et réutilisation d'email ;
- logs structurés ;
- compteurs existants ;
- test de rotation ;
- documentation utilisateur et opérateur.

### AW6 — Dépôts privés, après la V1

- GitHub App ;
- autorisation utilisateur ou organisation ;
- tokens courts ;
- clone privé ;
- push ;
- création de pull request ;
- broker de credentials évitant les tokens persistants dans le PVC.

## 26. Tests automatisés

### Django et services

- URL GitHub valide ;
- refus des schémas, hôtes, IP, ports, credentials, queries et fragments ;
- quota conservé ;
- verrou utilisateur conservé ;
- préfixe et noms déterministes ;
- dispatch Jupyter/Agent Workspace ;
- Launch idempotent ;
- échec Warpgate avant Helm sans workload ;
- échec Warpgate après Helm avec uninstall du workload et conservation du PVC ;
- échec Helm suivi du même rollback explicite ;
- rollback échoué donnant `UNKNOWN` et message d'erreur, jamais un succès ;
- Restart depuis STOPPED, FAILED et UNKNOWN ;
- Restart commençant par uninstall et s'arrêtant en `UNKNOWN` si celui-ci échoue ;
- Stop sans appel Warpgate ;
- Delete malgré Warpgate indisponible ;
- réconciliation des targets orphelines ;
- permission croisée entre utilisateurs ;
- synchronisation de l'email ;
- rafraîchissement de statut sans appel Warpgate ;
- indisponibilité Kubernetes affichée `UNKNOWN` sans écraser l'état persistant ;
- service persistant `UNKNOWN` jamais promu automatiquement depuis les Pods ;
- service `FAILED` sans Pod conservé en `FAILED` ;
- actions Stop/Restart/Delete visibles pour les bons statuts et slugs ;
- Jupyter ne propose Restart que pour `STOPPED` ;
- Agent Workspace propose Restart pour `STOPPED`, `FAILED` et `UNKNOWN` ;
- succès de Launch affiché uniquement pour `RUNNING` ;
- logs du bon conteneur ;
- init container en erreur.

### WarpgateClient

- timeouts ;
- TLS obligatoire ;
- CA personnalisée chargée et certificat invalide refusé ;
- token jamais loggé ;
- erreurs converties en exception métier ;
- `ensure_*` sans doublon ;
- conflit de création relu par nom ;
- email déjà rattaché au même utilisateur accepté de façon idempotente ;
- email rattaché à un autre utilisateur refusé sans déplacer le credential ;
- collision concurrente relue puis refusée ;
- mise à jour des objets divergents ;
- target SSH configurée avec DNS, port, utilisateur `developer` et clé publique ;
- réponses API invalides ;
- suppression d'une ressource absente acceptée.

### Keycloak et Warpgate

- le script configure un realm existant et reste idempotent au second passage ;
- le secret du client OIDC n'apparaît ni dans Git ni dans le ConfigMap ;
- un compte Ilosia `admin` ne possède aucun rôle `realm-management` ;
- HTTP impose SSO et SSH déclenche l'authentification navigateur ;
- un utilisateur ordinaire ne peut ajouter ni mot de passe, ni clé, ni API token ;
- une adresse désactivée ou déprovisionnée ne donne plus accès aux targets ;
- la commande refuse un utilisateur possédant encore un service non supprimé ;
- la commande supprime les targets résiduelles, credentials, liaisons, rôle et
  utilisateur Warpgate puis vérifie leur absence ;
- le déprovisionnement échoue sans autoriser la réutilisation si Warpgate est
  indisponible ou si le credential subsiste ;
- les logs de déprovisionnement ne contiennent pas l'email en clair ;
- un changement d'email exige une nouvelle connexion avant resynchronisation ;
- le back-channel logout invalide la session web OIDC et force une nouvelle
  authentification pour les prochaines approbations ;
- la révocation de rôle Warpgate lors du déprovisionnement ferme les sessions
  SSH actives.

### Helm

- `helm lint` ;
- Deployment `Recreate` ;
- Pod non-root ;
- root filesystem read-only ;
- `/tmp` et `/run` montés en `emptyDir` avec `sizeLimit` ;
- requests et limits de stockage éphémère ;
- aucune capability ;
- ServiceAccount token désactivé ;
- PVC `keep` ;
- Service 2222 ;
- readiness et liveness probes sur 2222 ;
- ingress SSH limité à Warpgate ;
- DNS uniquement vers CoreDNS ;
- egress privé et link-local refusé ;
- endpoint public du control plane refusé ;
- egress public limité aux ports décidés par AW0 ;
- clés publiques rendues dans `authorized_keys` ;
- identité Git rendue depuis les données serveur.

### E2E

Le script `scripts/check_agent_workspace.sh --e2e` doit :

1. créer deux utilisateurs temporaires ;
2. lancer un workspace par utilisateur ;
3. vérifier les PVC distincts ;
4. vérifier users, rôles, targets et liaisons Warpgate ;
5. vérifier l'absence d'accès croisé ;
6. modifier et committer un fichier ;
7. Stop puis Restart ;
8. vérifier le commit et la target inchangée ;
9. provoquer un rollback de provisioning et vérifier `FAILED` ;
10. provoquer un échec du cleanup et vérifier `UNKNOWN` sans faux succès ;
11. supprimer les services et données ;
12. exécuter le réconciliateur ;
13. vérifier l'absence de PVC et targets orphelines.

L'authentification navigateur Keycloak/Herdr reste un test manuel distinct tant
qu'aucun navigateur E2E n'existe dans le projet.

## 27. Définition de done

La V1 est terminée lorsque :

1. AW0 a produit une décision Go documentée ;
2. un utilisateur Keycloak vérifié peut lancer Agent Workspace ;
3. le verrou utilisateur et le quota existants restent appliqués ;
4. un dépôt public est cloné sur son PVC ;
5. Warpgate autorise uniquement le propriétaire ;
6. Herdr s'attache sans approbations répétées excessives ;
7. `codex login --device-auth` fonctionne ;
8. le mode sandbox Codex est explicite et testé ;
9. Codex peut modifier le dépôt et lancer ses tests ;
10. Git peut créer un commit local ;
11. detach/reattach conserve les processus pendant la vie du Pod ;
12. Stop conserve PVC, dépôt, commit, home et target Warpgate ;
13. Restart répare les ressources Warpgate et restaure l'accès ;
14. Restart fonctionne même si le ClusterIP a changé ;
15. Restart depuis FAILED répare un provisionnement partiel ;
16. Delete data supprime le PVC et la target ;
17. le réconciliateur supprime les targets orphelines ;
18. les init containers en erreur produisent `FAILED` ;
19. le pire lancement supporté reste sous le timeout ou le provisionnement est
    devenu asynchrone, et deux lancements ne bloquent pas l'interface ;
20. l'API Kubernetes, les nœuds et metadata cloud sont inaccessibles ;
21. GitHub, OpenAI et CoreDNS restent accessibles ;
22. le Pod n'a aucun token Kubernetes ni privilège root ;
23. la rotation de clé est testée et documentée ;
24. le stockage éphémère est borné et sshd est couvert par une readiness probe ;
25. le realm Keycloak existant est mis à jour sans recréation ;
26. les utilisateurs ordinaires ne peuvent pas contourner le SSO avec un autre
    credential Warpgate ;
27. la sauvegarde Warpgate a été restaurée et une target a été rejointe ;
28. un rollback incomplet reste `UNKNOWN` jusqu'à une réparation explicite et
    ne produit jamais un faux `RUNNING` ;
29. une collision d'email Warpgate échoue sans déplacer le credential et le
    déprovisionnement vérifie sa disparition avant toute réutilisation ;
30. Jupyter conserve Restart uniquement depuis `STOPPED` ;
31. tests Django, tests Helm, CI et E2E sont verts.

## 28. Références

- [Herdr — persistence and remote access](https://herdr.dev/docs/persistence-remote/)
- [Herdr — session state and restore](https://herdr.dev/docs/session-state/)
- [Warpgate — SSO](https://warpgate.null.page/sso/)
- [Warpgate — user authentication](https://warpgate.null.page/auth/)
- [Warpgate — SSH targets](https://warpgate.null.page/targets/ssh/)
- [Warpgate — Helm](https://warpgate.null.page/getting-started-on-helm/)
- [Warpgate — clustering](https://warpgate.null.page/clustering/)
- [Warpgate — backup and restore](https://warpgate.null.page/backup/)
- [Warpgate — production checklist](https://warpgate.null.page/production-checklist/)
- [Keycloak — realm import](https://www.keycloak.org/server/importExport)
- [Keycloak — Update Email workflow](https://www.keycloak.org/docs/latest/server_admin/index.html#update-email-workflow-updateemail)
- [Kubernetes — NetworkPolicy](https://kubernetes.io/docs/concepts/services-networking/network-policies/)
- [OpenAI — sandbox security](https://developers.openai.com/api/docs/guides/agents-api/environments/security)
- [OpenAI — loopback OAuth callback](https://developers.openai.com/siwc/token-sharing-open-source/sign-in)
- [Scaleway — Metadata API](https://www.scaleway.com/en/docs/instances/how-to/use-cloud-init/#querying-meta-data-from-within-the-instance)
- [Scaleway — control plane allowed IPs](https://www.scaleway.com/en/docs/kubernetes/how-to/manage-allowed-ips/)
- [Scaleway — VPC DNS](https://www.scaleway.com/en/docs/vpc/reference-content/dns/)
