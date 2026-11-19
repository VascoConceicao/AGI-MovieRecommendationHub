# Same contract as infra/terraform/cluster: external addresses feed the
# Ansible inventory (SSH/scp/kubeconfig server); kubeadm advertises the
# external control-plane address, so site.yaml runs unchanged.
output "control_plane_ips" {
  description = "Control-plane external addresses for the Ansible inventory."
  value       = [google_compute_address.control_plane.address]
}

output "worker_ips" {
  description = "Worker external addresses for the Ansible inventory."
  value       = google_compute_instance.worker[*].network_interface[0].access_config[0].nat_ip
}

output "control_plane_internal_ips" {
  description = "Control-plane internal addresses (debugging/pod traffic)."
  value       = google_compute_instance.control_plane[*].network_interface[0].network_ip
}

output "worker_internal_ips" {
  description = "Worker internal addresses (debugging/pod traffic)."
  value       = google_compute_instance.worker[*].network_interface[0].network_ip
}

output "kubeconfig_path" {
  description = "Expected kubeconfig path produced by the Ansible kubeadm step (server URL rewritten to the external address)."
  value       = "${path.module}/kubeconfig.out"
}
