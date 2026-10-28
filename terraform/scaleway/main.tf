resource "scaleway_vpc_private_network" "ilosia" {
  name = "${var.cluster_name}-private-network"
  tags = ["ilosia", "terraform"]
}

resource "scaleway_k8s_cluster" "ilosia" {
  name                        = var.cluster_name
  type                        = "kapsule"
  version                     = var.kubernetes_version
  cni                         = "cilium"
  private_network_id          = scaleway_vpc_private_network.ilosia.id
  delete_additional_resources = false
  tags                        = ["ilosia", "terraform"]
}

resource "scaleway_k8s_pool" "workers" {
  cluster_id  = scaleway_k8s_cluster.ilosia.id
  name        = "workers"
  node_type   = var.node_type
  size        = var.node_count
  autohealing = true
}

