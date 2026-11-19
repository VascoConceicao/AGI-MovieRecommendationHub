#!/bin/sh
# Demo baseline / acceptance gate for the g15 platform.
# Read-only: asserts desired state, changes nothing. Safe to run repeatedly
# (before/after any change, or as a CI gate later).
#
# Usage (repository root):
#   sh infra/tests/demo-check.sh
# All three environment variables default sensibly (local cluster,
# control-plane NodePort, ~/.ssh/id_ed25519.pub); export to override.
#
# Exit 0 only if every check passes.
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)

# Sensible defaults; override by exporting beforehand.
: "${KUBECONFIG:=$SCRIPT_DIR/../terraform/cluster/kubeconfig.out}"
: "${NODE_IP:=10.42.42.222}"
export KUBECONFIG NODE_IP
export TF_VAR_ssh_public_key="${TF_VAR_ssh_public_key:-$(cat ~/.ssh/id_ed25519.pub 2>/dev/null || true)}"

for tool in kubectl curl python3 terraform; do
  if ! command -v "$tool" >/dev/null 2>&1; then
    echo "FAIL - required tool missing: $tool" >&2
    exit 2
  fi
done

PASS=0
FAIL=0

ok() {
  PASS=$((PASS + 1))
  echo "ok   - $1"
}

bad() {
  FAIL=$((FAIL + 1))
  echo "FAIL - $1"
}

# 1. Nodes: exactly 3, all Ready.
NODES_READY=$(kubectl get nodes --no-headers 2>/dev/null | awk '$2=="Ready"' | wc -l)
if [ "$NODES_READY" -eq 3 ]; then
  ok "3/3 nodes Ready"
else
  bad "nodes Ready: $NODES_READY (want 3)"
fi

# 2. Namespaces exist.
for ns in g15-app g15-monitoring ingress-nginx; do
  if kubectl get namespace "$ns" >/dev/null 2>&1; then
    ok "namespace $ns exists"
  else
    bad "namespace $ns missing"
  fi
done

# 3. All pods ready, PVCs bound.
for ns in g15-app g15-monitoring ingress-nginx; do
  if kubectl -n "$ns" wait --for=condition=ready pod --all --timeout=120s >/dev/null 2>&1; then
    ok "all pods ready in $ns"
  else
    bad "pods not ready in $ns"
  fi
done
UNBOUND=$(kubectl -n g15-app get pvc --no-headers 2>/dev/null | awk '$2!="Bound" || $2=="" {n++} END {print n+0}')
if [ "$UNBOUND" -eq 0 ] && [ "$(kubectl -n g15-app get pvc --no-headers 2>/dev/null | wc -l)" -gt 0 ]; then
  ok "all PVCs Bound"
else
  bad "$UNBOUND PVCs unbound (or none present)"
fi

# 4. Application through the ingress entrypoint (:30080 → proxy Ingress → proxy).
for svc in movie recommendation user; do
  BODY=$(curl -s -m 10 "http://$NODE_IP:30080/api/$svc/health" 2>/dev/null | tr -d ' ' || true)
  case "$BODY" in
    *'"status":"ok"'*)
      case "$BODY" in
        *'"database":"up"'*)
          ok "$svc health ok through ingress"
          ;;
        *)
          bad "$svc health unexpected: $BODY"
          ;;
      esac
      ;;
    *)
      bad "$svc health unexpected: $BODY"
      ;;
  esac
done
if curl -s -m 10 -o /dev/null -w "%{http_code}" "http://$NODE_IP:30080/" 2>/dev/null | grep -q 200; then
  ok "frontend serves 200 through ingress"
else
  bad "frontend not serving through ingress"
fi
if kubectl -n g15-app get ingress/proxy >/dev/null 2>&1; then
  ok "proxy Ingress present"
else
  bad "proxy Ingress missing"
fi

# 5. Prometheus scrapes all three backends.
kubectl -n g15-monitoring port-forward svc/kube-prometheus-stack-prometheus 9090:9090 >/dev/null 2>&1 &
PF_PID=$!
trap 'kill $PF_PID 2>/dev/null' EXIT INT TERM
sleep 5
TARGETS=$(python3 -c "
import json, urllib.request
d = json.load(urllib.request.urlopen('http://127.0.0.1:9090/api/v1/targets?state=active', timeout=20))
up = sorted(t['labels'].get('service') for t in d['data']['activeTargets'] if 'g15-backend' in t['scrapePool'] and t['health'] == 'up')
print(' '.join(up))
" 2>/dev/null || true)
if [ "$TARGETS" = "movie-service recommendation-service user-service" ]; then
  ok "Prometheus scrapes all 3 backends (up)"
else
  bad "Prometheus backend targets: '$TARGETS'"
fi
kill "$PF_PID" 2>/dev/null || true
trap - EXIT INT TERM

# 5b. Logging (Loki + Alloy) and ingress controller.
for obj in "statefulset/loki" "daemonset/alloy" "svc/loki"; do
  if kubectl -n g15-monitoring get "$obj" >/dev/null 2>&1; then
    ok "logging $obj present"
  else
    bad "logging $obj missing"
  fi
done
if kubectl -n ingress-nginx get svc/ingress-nginx-controller >/dev/null 2>&1; then
  ok "ingress-nginx-controller Service present"
else
  bad "ingress-nginx-controller Service missing"
fi
kubectl -n g15-monitoring port-forward svc/loki 3100:3100 >/dev/null 2>&1 &
PF_PID=$!
trap 'kill $PF_PID 2>/dev/null' EXIT INT TERM
sleep 5
if curl -s -m 10 http://127.0.0.1:3100/ready 2>/dev/null | grep -q ready; then
  ok "Loki ready"
else
  bad "Loki not ready"
fi
kill "$PF_PID" 2>/dev/null || true
trap - EXIT INT TERM

# 6. IaC idempotency: both layers plan-clean (proves reproducible state).
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
if (cd "$ROOT" && terraform -chdir=infra/terraform/cluster plan -detailed-exitcode -no-color >/dev/null 2>&1); then
  PLAN_RC=0
else
  PLAN_RC=$?
fi
if [ "$PLAN_RC" -eq 0 ]; then
  ok "terraform cluster plan clean"
elif [ "$PLAN_RC" -eq 2 ]; then
  bad "terraform cluster plan has changes"
else
  bad "terraform cluster plan errored"
fi
if (cd "$ROOT" && terraform -chdir=infra/terraform/app plan -detailed-exitcode -no-color >/dev/null 2>&1); then
  PLAN_RC=0
else
  PLAN_RC=$?
fi
if [ "$PLAN_RC" -eq 0 ]; then
  ok "terraform app plan clean"
elif [ "$PLAN_RC" -eq 2 ]; then
  bad "terraform app plan has changes"
else
  bad "terraform app plan errored"
fi

echo "---"
echo "pass=$PASS fail=$FAIL"
[ "$FAIL" -eq 0 ]
