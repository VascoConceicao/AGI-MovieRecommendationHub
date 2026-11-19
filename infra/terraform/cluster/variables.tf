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

variable "base_image" {
  description = "Local libvirt base image (Ubuntu 24.04 cloud image path)."
  type        = string
  default     = "/var/lib/libvirt/images/ubuntu-24.04-server-cloudimg-amd64.img"
}

variable "vm_memory_mb" {
  description = "RAM per VM in MB."
  type        = number
  default     = 2048
}

variable "vm_vcpu" {
  description = "vCPUs per VM."
  type        = number
  default     = 2
}

variable "libvirt_uri" {
  description = "Libvirt connection URI for local KVM."
  type        = string
  default     = "qemu:///system"
}

variable "network_cidr" {
  description = "CIDR for the dedicated NAT network."
  type        = string
  default     = "10.42.42.0/24"
}

variable "node_disk_bytes" {
  description = "Root disk size per VM in bytes (20 GiB default)."
  type        = number
  default     = 21474836480
}

variable "worker_macs" {
  description = "Pinned MAC addresses for worker VMs (must match worker_count). Pinning keeps VM identity deterministic across recreation."
  type        = list(string)
  default     = ["52:54:00:6A:4F:21", "52:54:00:BA:9E:4B"]

  validation {
    condition     = length(var.worker_macs) == var.worker_count
    error_message = "worker_macs must contain exactly worker_count entries."
  }
}

variable "ssh_public_key" {
  description = "SSH public key installed on the ubuntu user via cloud-init."
  type        = string
  default     = ""

  validation {
    condition     = length(var.ssh_public_key) > 0
    error_message = "Set ssh_public_key (e.g. -var-file or TF_VAR_ssh_public_key); key-based SSH is required."
  }
}
