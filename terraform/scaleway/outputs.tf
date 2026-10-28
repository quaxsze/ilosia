output "cluster_id" {
  description = "Regional Scaleway cluster ID."
  value       = scaleway_k8s_cluster.ilosia.id
}

output "api_server_url" {
  description = "Kubernetes API endpoint."
  value       = scaleway_k8s_cluster.ilosia.apiserver_url
}

output "kubeconfig" {
  description = "Raw kubeconfig; write it only to a protected local file."
  value       = scaleway_k8s_cluster.ilosia.kubeconfig[0].config_file
  sensitive   = true
}

