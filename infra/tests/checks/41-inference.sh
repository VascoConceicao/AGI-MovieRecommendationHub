#!/bin/sh
# Inference engine actively used by backends (Martim's track).
CHECK_NAME="inference"
. "$TESTS_DIR/lib.sh"
need kubectl
if kubectl get deployment,statefulset,service --all-namespaces --no-headers 2>/dev/null | grep -iE "infer|model|triton|ollama|vllm" | head -n 3 | grep -q .; then
  pass "inference workload present"
else
  skip "no inference engine deployed yet (Martim)"
fi
