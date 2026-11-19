variable "project" {
  description = "GCP project hosting the cluster."
  type        = string
  default     = "g15-mlops"
}

variable "region" {
  description = "GCP region (Madrid, closest to Lisbon)."
  type        = string
  default     = "europe-southwest1"
}

variable "zone" {
  description = "GCP zone for all three nodes (single-zone keeps the demo simple)."
  type        = string
  default     = "europe-southwest1-a"
}

variable "control_plane_count" {
  description = "Number of kubeadm control-plane VMs (single control-plane; HA is out of scope)."
  type        = number
  default     = 1
}

variable "worker_count" {
  description = "Number of kubeadm worker VMs."
  type        = number
  default     = 2
}

variable "machine_type" {
  description = "GCE machine type for each node (e2-standard-2 provides 2 vCPU / 8 GiB)."
  type        = string
  default     = "e2-standard-2"
}

variable "disk_size_gb" {
  description = "Boot disk size per VM in GB (balanced persistent disk)."
  type        = number
  default     = 20
}

variable "subnet_cidr" {
  description = "Node subnet CIDR (kept identical to local for familiarity)."
  type        = string
  default     = "10.42.42.0/24"
}

variable "control_plane_ip" {
  description = "Static internal IP for the control-plane node."
  type        = string
  default     = "10.42.42.10"
}

variable "worker_ips" {
  description = "Static internal IPs for worker nodes (must match worker_count)."
  type        = list(string)
  default     = ["10.42.42.11", "10.42.42.12"]

  validation {
    condition     = length(var.worker_ips) == var.worker_count
    error_message = "worker_ips must contain exactly worker_count entries."
  }
}

variable "ssh_public_key" {
  description = "SSH public key installed on the ubuntu user via instance metadata."
  type        = string
  default     = ""

  validation {
    condition     = length(var.ssh_public_key) > 0
    error_message = "Set ssh_public_key (e.g. -var-file or TF_VAR_ssh_public_key); key-based SSH is required."
  }
}

variable "additional_operator_cidrs" {
  description = "Additional public IPv4 addresses with the same SSH, Kubernetes API, and app access as the operator."
  type        = list(string)
  default     = ["87.196.85.136/32", "89.115.96.14/32", "85.246.209.178/32"]

  validation {
    condition     = alltrue([for cidr in var.additional_operator_cidrs : can(cidrnetmask(cidr)) && endswith(cidr, "/32")])
    error_message = "Each additional operator must use an IPv4 address with a /32 suffix."
  }
}

variable "app_client_cidrs" {
  description = "Additional public IPv4 addresses allowed to access the app on port 30080."
  type        = list(string)
  default     = []

  validation {
    condition     = alltrue([for cidr in var.app_client_cidrs : can(cidrnetmask(cidr)) && endswith(cidr, "/32")])
    error_message = "Each app client must be a public IPv4 address with a /32 suffix."
  }
}

variable "operator_cidr" {
  description = "Operator public IP in CIDR notation (e.g. 203.0.113.7/32). Scopes SSH, API, and NodePort access."
  type        = string
  default     = ""

  validation {
    condition     = length(var.operator_cidr) > 0
    error_message = "Set operator_cidr to your public IP; management ports are never opened to the world."
  }
}
