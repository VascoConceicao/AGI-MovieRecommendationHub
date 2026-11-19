variable "kubeconfig_path" {
  description = "Kubeconfig produced by a cluster layer (../cluster or ../cluster-gcp kubeconfig.out)."
  type        = string
  default     = "../cluster/kubeconfig.out"
}

variable "app_namespace" {
  description = "Namespace for movie/user/recommendation services and proxy."
  type        = string
  default     = "g15-app"
}

variable "monitoring_namespace" {
  description = "Namespace for the kube-prometheus-stack release."
  type        = string
  default     = "g15-monitoring"
}

variable "prometheus_values_file" {
  description = "Helm values file for kube-prometheus-stack."
  type        = string
  default     = "../../k8s/monitoring/prometheus-values.yaml"
}

variable "monitoring_chart_version" {
  description = "Pinned kube-prometheus-stack chart version."
  type        = string
  default     = "91.5.0"
}

variable "loki_chart_version" {
  description = "Pinned Loki chart version."
  type        = string
  default     = "7.3.0"
}

variable "alloy_chart_version" {
  description = "Pinned Alloy chart version."
  type        = string
  default     = "1.13.0"
}

variable "ingress_chart_version" {
  description = "Pinned ingress-nginx chart version."
  type        = string
  default     = "4.15.1"
}

variable "loki_values_file" {
  description = "Helm values file for Loki."
  type        = string
  default     = "../../k8s/monitoring/loki-values.yaml"
}

variable "alloy_values_file" {
  description = "Helm values file for Alloy."
  type        = string
  default     = "../../k8s/monitoring/alloy-values.yaml"
}

variable "ingress_values_file" {
  description = "Helm values file for ingress-nginx."
  type        = string
  default     = "../../k8s/ingress/values.yaml"
}

variable "ingress_namespace" {
  description = "Namespace for the ingress-nginx release."
  type        = string
  default     = "ingress-nginx"
}
