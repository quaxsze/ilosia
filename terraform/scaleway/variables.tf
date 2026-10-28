variable "project_id" {
  description = "Scaleway project receiving the Kapsule resources."
  type        = string
}

variable "region" {
  description = "Scaleway region."
  type        = string
  default     = "fr-par"
}

variable "cluster_name" {
  description = "Kapsule cluster name."
  type        = string
  default     = "ilosia"
}

variable "kubernetes_version" {
  description = "Pinned Kubernetes version supported by Kapsule."
  type        = string
  default     = "1.35.3"
}

variable "node_type" {
  description = "Scaleway instance type used by the worker pool."
  type        = string
  default     = "DEV1-M"
}

variable "node_count" {
  description = "Initial worker count; increasing it changes monthly cost."
  type        = number
  default     = 1

  validation {
    condition     = var.node_count >= 1
    error_message = "node_count must be at least 1."
  }
}

