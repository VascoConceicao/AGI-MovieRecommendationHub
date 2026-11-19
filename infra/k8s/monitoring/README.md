# Monitoring stack (`feat(monitoring)` commits)

`kube-prometheus-stack`, Loki, Alloy, and ingress-nginx are deployed by
Terraform (`infra/terraform/app`: `helm_release.monitoring`, `helm_release.loki`,
`helm_release.alloy`, `helm_release.ingress`), not by hand. Prometheus scrapes
Kubernetes metrics and the Flask `/metrics` endpoints; Alloy ships pod logs to
Loki; Grafana serves the provisioned "G15 Services" dashboard with a
preconfigured Loki datasource. Ingress-nginx (`:30080`) fronts the proxy
Ingress; the proxy Service itself is ClusterIP.

## What's deployed

- Chart `kube-prometheus-stack` pinned in `monitoring_chart_version`
  (currently 91.5.0), values in `infra/k8s/monitoring/prometheus-values.yaml`:
  2-day retention, **no persistent storage** (declared choice, not an
  accident), alertmanager off, kube-state-metrics + node-exporter on.
  Grafana gains a `Loki` datasource (`http://loki:3100`).
- Chart `loki` pinned in `loki_chart_version` (currently 7.3.0), values in
  `infra/k8s/monitoring/loki-values.yaml`: single-binary, 1 replica, 1 GiB
  local-path PVC, 48h compactor retention.
- Chart `alloy` pinned in `alloy_chart_version` (currently 1.13.0), values in
  `infra/k8s/monitoring/alloy-values.yaml`: DaemonSet (with control-plane
  toleration) shipping `/var/log/pods` to `http://loki:3100/loki/api/v1/push`.
- Chart `ingress-nginx` pinned in `ingress_chart_version` (currently 4.15.1),
  values in `infra/k8s/ingress/values.yaml`: single replica, NodePort
  `:30080`/`:30443`, admission webhooks on. The `proxy` Ingress
  (`infra/k8s/app/proxy/ingress.yaml`, applied via `kubectl -k infra/k8s/app`)
  routes `/` to the proxy Service.
- `ServiceMonitor/g15-backend` (Terraform `kubernetes_manifest`): selects
  `app.kubernetes.io/part-of: g15` in `g15-app` on the `http` port. Only
  the three backends name a port `http`, so only they produce targets.
- Dashboard `G15 Services` (`grafana-dashboard.json`): request rate, p95
  latency, 4xx/5xx share, DB health, scrape targets, plus an application-logs
  panel (`{namespace="g15-app"}` via the Loki datasource). Provisioned as the
  `g15-services-dashboard` ConfigMap (`grafana_dashboard=1` label) via
  Terraform; the sidecar imports it automatically. Recreating the
  ConfigMap through Terraform restores the dashboard — verified.

## Application metrics

Backends expose, per service (`g15_common.monitoring.metrics`, single-worker
gunicorn so counters stay correct):

```text
g15_http_requests_total{service,method,route,status}
g15_http_request_duration_seconds_bucket{service,method,route,le}
g15_db_up{service}
```

Contract for future product work (Vasco/Martim — not implemented yet):

```text
g15_recommendations_generated_total{service}
g15_recommendation_generation_seconds_bucket{service,le}
g15_recommendation_cache_hits_total / _misses_total{service}
g15_inference_requests_total / g15_inference_latency_seconds_bucket
```

## Image side-loading

On the local KVM/libvirt cluster the nodes have no registry egress, so
monitoring images use the same tarball + `ctr import` flow as the app
(see `infra/k8s/app/README.md`). The GCP nodes have full egress and pull
upstream images directly, so no side-loading is needed there. Current
set for the local flow (exact tags from the deployed release — read them
from failing Pod specs if the chart version changes):

```text
quay.io/prometheus-operator/prometheus-operator:v0.94.0
quay.io/prometheus/prometheus:v3.14.0-distroless
quay.io/prometheus-operator/prometheus-config-reloader:v0.94.0
docker.io/grafana/grafana:13.2.2-distroless
quay.io/kiwigrid/k8s-sidecar:2.11.2
registry.k8s.io/kube-state-metrics/kube-state-metrics:v2.20.0
quay.io/prometheus/node-exporter:v1.12.1-distroless
ghcr.io/jkroepke/kube-webhook-certgen:1.8.8
docker.io/library/busybox:latest   # local-path-provisioner helper pods
```

Caveats learned the hard way:

- Save and verify **one image per tarball**, then distribute. A combined
  `docker save` once produced an archive referencing a missing blob, and
  `docker save` silently emits layerless archives for zstd-layered images
  (kube-state-metrics v2.20.0) — recovered with `crane pull --format legacy`.
- `kubectl get pods -n g15-monitoring -o jsonpath=...{.image...}` is the
  source of truth for the exact list after any chart bump.
- Alloy discovery is cluster-wide with no node filter, so every replica
  re-opens every pod's stream (hundreds of `opened log stream` lines per
  minute in Alloy logs) while only the pod's own node can actually tail
  its file. Noisy but harmless: local files are tailed and all 8 `g15-app`
  streams land in Loki (verified via `/loki/api/v1/series`). The proper
  fix is a node-name `keep` rule in `alloy-values.yaml`; left out
  deliberately before the demo (unverified chart value schema).

## Verify

```sh
KUBECONFIG=infra/terraform/cluster/kubeconfig.out
kubectl -n g15-monitoring get pods
curl -s "http://127.0.0.1:9090/api/v1/query?query=sum(g15_http_requests_total)"  # via port-forward 9090
curl -s -u admin:g15-local-only http://127.0.0.1:3000/api/search?query=g15      # via port-forward 3000
curl -s "http://127.0.0.1:3100/ready"                                          # via port-forward 3100 (loki)
curl -s "http://127.0.0.1:3100/loki/api/v1/query_range?query={namespace=\"g15-app\"}"  # logs flowing via Alloy
kubectl -n ingress-nginx get svc ingress-nginx-controller -o jsonpath='{.spec.ports}'
```

Chart-default `down` targets (scheduler/etcd/proxy/controller-manager)
are upstream defaults for this kubeadm shape — out of scope, untouched.
