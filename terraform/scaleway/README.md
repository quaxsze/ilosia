# Infrastructure Scaleway

Ce module crée uniquement l'infrastructure externe : un réseau privé, un
cluster Kapsule et son pool de workers. Helm et Argo CD restent responsables des
applications. Le nombre de nœuds par défaut est volontairement limité à un pour
maîtriser le coût d'apprentissage.

Terraform crée des ressources facturées. Lire le plan avant toute application :

```bash
cd terraform/scaleway
cp terraform.tfvars.example terraform.tfvars
export SCW_ACCESS_KEY='<access-key>'
export SCW_SECRET_KEY='<secret-key>'

terraform init
terraform fmt -check
terraform validate
terraform plan -out=ilosia.tfplan
terraform apply ilosia.tfplan
```

Récupérer ensuite le kubeconfig sans le committer :

```bash
terraform output -raw kubeconfig > /tmp/ilosia-kubeconfig.yaml
chmod 600 /tmp/ilosia-kubeconfig.yaml
KUBECONFIG=/tmp/ilosia-kubeconfig.yaml kubectl get nodes
```

L'état Terraform est local pour ce prototype. Avant un usage en équipe, le
déplacer vers un backend distant chiffré et verrouillé. `destroy` ne supprime pas
automatiquement les volumes et load balancers additionnels du cluster car
`delete_additional_resources` vaut `false`.

