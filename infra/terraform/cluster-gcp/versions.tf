# Layer 1 (GCP): GCE VMs for a self-hosted kubeadm cluster.
# Mirrors infra/terraform/cluster outputs so Ansible and the app layer
# work unchanged. No managed Kubernetes (GKE) anywhere in this path.
terraform {
  required_version = ">= 1.9.0"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 8.0"
    }
  }
}
