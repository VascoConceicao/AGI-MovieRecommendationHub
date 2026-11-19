provider "kubernetes" {
  config_path = var.kubeconfig_path
}

provider "helm" {
  kubernetes {
    config_path = var.kubeconfig_path
  }
}

resource "kubernetes_namespace" "app" {
  metadata {
    name = var.app_namespace
    labels = {
      "app.kubernetes.io/part-of" = "g15"
    }
  }
}

resource "kubernetes_namespace" "monitoring" {
  metadata {
    name = var.monitoring_namespace
    labels = {
      "app.kubernetes.io/part-of" = "g15"
    }
  }
}

resource "kubernetes_namespace" "ingress" {
  metadata {
    name = var.ingress_namespace
    labels = {
      "app.kubernetes.io/part-of" = "g15"
    }
  }
}

resource "helm_release" "monitoring" {
  name       = "kube-prometheus-stack"
  repository = "https://prometheus-community.github.io/helm-charts"
  chart      = "kube-prometheus-stack"
  version    = var.monitoring_chart_version
  namespace  = kubernetes_namespace.monitoring.metadata[0].name

  values = [
    file(var.prometheus_values_file),
  ]

  timeout = 600
}

resource "helm_release" "loki" {
  name       = "loki"
  repository = "https://grafana.github.io/helm-charts"
  chart      = "loki"
  version    = var.loki_chart_version
  namespace  = kubernetes_namespace.monitoring.metadata[0].name

  values = [
    file(var.loki_values_file),
  ]

  timeout = 600
}

resource "helm_release" "alloy" {
  name       = "alloy"
  repository = "https://grafana.github.io/helm-charts"
  chart      = "alloy"
  version    = var.alloy_chart_version
  namespace  = kubernetes_namespace.monitoring.metadata[0].name

  values = [
    file(var.alloy_values_file),
  ]

  timeout = 600
}

resource "helm_release" "ingress" {
  name       = "ingress-nginx"
  repository = "https://kubernetes.github.io/ingress-nginx"
  chart      = "ingress-nginx"
  version    = var.ingress_chart_version
  namespace  = kubernetes_namespace.ingress.metadata[0].name

  values = [
    file(var.ingress_values_file),
  ]

  timeout = 600
}

resource "kubernetes_manifest" "backend_servicemonitor" {
  manifest = yamldecode(file("${path.module}/../../k8s/monitoring/servicemonitor.yaml"))

  depends_on = [helm_release.monitoring]
}

resource "kubernetes_config_map" "grafana_dashboard" {
  metadata {
    name      = "g15-services-dashboard"
    namespace = kubernetes_namespace.monitoring.metadata[0].name
    labels = {
      "app.kubernetes.io/part-of" = "g15"
      "grafana_dashboard"         = "1"
    }
  }

  data = {
    "g15-services.json" = file("${path.module}/../../k8s/monitoring/grafana-dashboard.json")
  }

  depends_on = [helm_release.monitoring]
}
