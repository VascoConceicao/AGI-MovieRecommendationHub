output "app_namespace" {
  description = "Namespace the full implementation deploys the application into."
  value       = var.app_namespace
}

output "monitoring_namespace" {
  description = "Namespace hosting Prometheus, Grafana, Loki, and Alloy."
  value       = var.monitoring_namespace
}

output "ingress_namespace" {
  description = "Namespace hosting the ingress-nginx controller."
  value       = var.ingress_namespace
}

output "grafana_access" {
  description = "Grafana port-forward (admin password is the local-only default in prometheus-values.yaml)."
  value       = "kubectl -n ${var.monitoring_namespace} port-forward svc/kube-prometheus-stack-grafana 3000:80"
}

output "loki_access" {
  description = "Loki readiness and log query (via port-forward 3100)."
  value       = "kubectl -n ${var.monitoring_namespace} port-forward svc/loki 3100:3100"
}

output "app_entrypoint" {
  description = "Application entrypoint through the ingress-nginx NodePort."
  value       = "curl http://<any-node-ip>:30080/api/movie/health"
}
