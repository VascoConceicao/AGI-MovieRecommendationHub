#!/bin/sh
# Graded public-cloud deployment. Runs only when pointed at one.
CHECK_NAME="public-cloud"
. "$TESTS_DIR/lib.sh"
need kubectl
if [ -n "${GCE_KUBECONFIG:-}" ] && [ -f "${GCE_KUBECONFIG:-}" ]; then
  if KUBECONFIG="$GCE_KUBECONFIG" kubectl get nodes --no-headers 2>/dev/null | awk '$2!="Ready" {bad=1} END {exit bad+0}'; then
    pass "graded-cloud cluster reachable, nodes Ready (via GCE_KUBECONFIG)"
  else
    fail "graded-cloud cluster unreachable or nodes unready"
  fi
else
  skip "no graded-cloud kubeconfig (set GCE_KUBECONFIG to enable; GCE was verified then destroyed)"
fi
