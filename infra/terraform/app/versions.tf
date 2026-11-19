# Layer 2: namespaces, monitoring/logging/ingress releases, and monitoring
# objects on top of an existing cluster. Consumes a cluster layer kubeconfig
# (../cluster or ../cluster-gcp kubeconfig.out, via kubeconfig_path).
# Application workloads in k8s/app deploy with kubectl; this layer owns
# namespaces, the kube-prometheus-stack + Loki + Alloy + ingress-nginx Helm
# releases, the ServiceMonitor, and the Grafana dashboard ConfigMap.
# No manual kubectl steps.
terraform {
  required_version = ">= 1.9.0"
  required_providers {
    helm = {
      source  = "hashicorp/helm"
      version = "~> 2.14"
    }
    kubernetes = {
      source  = "hashicorp/kubernetes"
      version = "~> 2.32"
    }
  }
}
