#!/bin/sh
# Self-hosted Kubernetes only: kubeadm bootstrap present, no managed
# control plane (GKE/EKS/AKS) labels anywhere on nodes.
CHECK_NAME="self-hosted-cluster"
. "$TESTS_DIR/lib.sh"
need kubectl
kubectl get configmap kubeadm-config -n kube-system >/dev/null 2>&1 \
  || fail "kubeadm-config ConfigMap missing (not a kubeadm cluster?)"
if kubectl get nodes -o json 2>/dev/null | python3 -c "
import json,sys
labels = [l for n in json.load(sys.stdin)['items'] for l in n['metadata'].get('labels', {})]
bad = [l for l in labels if any(k in l for k in ('eks.amazonaws', 'gke', 'aks.azure', 'managed'))]
sys.exit(1 if bad else 0)
"; then
  pass "kubeadm-config present, no managed-K8s node labels"
else
  fail "managed-Kubernetes node labels detected"
fi
