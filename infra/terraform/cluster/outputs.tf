output "control_plane_ips" {
  description = "Control-plane VM addresses for the Ansible inventory."
  value       = [for d in libvirt_domain.control_plane : d.network_interface[0].addresses[0]]
}

output "worker_ips" {
  description = "Worker VM addresses for the Ansible inventory."
  value       = [for d in libvirt_domain.worker : d.network_interface[0].addresses[0]]
}

output "kubeconfig_path" {
  description = "Expected kubeconfig path produced by the Ansible kubeadm step."
  value       = "${path.module}/kubeconfig.out"
}
