# Layer 1: local VMs for a self-hosted kubeadm cluster.
# Provider: libvirt/KVM for zero-cost local verification. Pinned to the 0.8
# series: 0.9.x rewrote the resource schema (flat libvirt-XML attributes),
# which this configuration does not use.
# Cloud migration: add terraform/cluster-aws (EC2 VMs, same outputs) and keep
# this module's outputs (kubeconfig path, control-plane IP, worker IPs) stable.
terraform {
  required_version = ">= 1.9.0"

  required_providers {
    libvirt = {
      source  = "dmacvicar/libvirt"
      version = "~> 0.8.0"
    }
  }
}
