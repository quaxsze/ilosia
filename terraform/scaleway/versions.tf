terraform {
  required_version = ">= 1.5.0"

  required_providers {
    scaleway = {
      source  = "scaleway/scaleway"
      version = "~> 2.84.0"
    }
  }
}

provider "scaleway" {
  project_id = var.project_id
  region     = var.region
}

