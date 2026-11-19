#!/bin/sh
# Monitoring chain live: Prometheus targets, dashboard provisioned,
# logs flowing (Loki + Alloy), ingress entrypoint present.
CHECK_NAME="monitoring-chain"
. "$TESTS_DIR/lib.sh"
need kubectl
for obj in "servicemonitor/g15-backend" "configmap/g15-services-dashboard"; do
  kubectl -n g15-monitoring get "$obj" >/dev/null 2>&1 \
    || fail "missing $obj"
done
for obj in "statefulset/loki" "daemonset/alloy" "svc/loki"; do
  kubectl -n g15-monitoring get "$obj" >/dev/null 2>&1 \
    || fail "missing logging $obj (helm_release loki/alloy?)"
done
kubectl -n ingress-nginx get svc/ingress-nginx-controller >/dev/null 2>&1 \
  || fail "missing ingress-nginx-controller Service (helm_release ingress?)"
kubectl -n g15-app get ingress/proxy >/dev/null 2>&1 \
  || fail "missing proxy Ingress (kubectl apply -k infra/k8s/app?)"
up=$(kubectl -n g15-monitoring port-forward svc/kube-prometheus-stack-prometheus 9090:9090 >/dev/null 2>&1 & PF=$!; sleep 5; python3 -c "
import json, urllib.request
d = json.load(urllib.request.urlopen('http://127.0.0.1:9090/api/v1/targets?state=active', timeout=20))
ups = [t for t in d['data']['activeTargets'] if 'g15-backend' in t['scrapePool'] and t['health'] == 'up']
print(len(ups))
" 2>/dev/null; kill $PF 2>/dev/null; true)
[ "$up" = "3" ] || fail "backend targets up: '$up' (want 3)"
ready=$(kubectl -n g15-monitoring port-forward svc/loki 3100:3100 >/dev/null 2>&1 & PF=$!; sleep 5; curl -s -m 10 http://127.0.0.1:3100/ready 2>/dev/null; kill $PF 2>/dev/null; true)
case "$ready" in
  *ready*) ;;
  *) fail "loki not ready (got '$ready')" ;;
esac
pass "ServiceMonitor + dashboard + Loki/Alloy + ingress present, 3/3 backend targets up, Loki ready"
