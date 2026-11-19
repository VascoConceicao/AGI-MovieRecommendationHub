#!/bin/sh
# Demo gate as one battery item (nodes, namespaces, pods, ingress entrypoint,
# Prometheus targets, Loki logging, plan-clean).
CHECK_NAME="demo-gate"
need() { command -v "$1" >/dev/null 2>&1 || { echo "FAIL: $CHECK_NAME - missing tool $1"; exit 1; }; }
need kubectl
if sh "$TESTS_DIR/demo-check.sh" >/dev/null 2>&1; then
  echo "PASS: $CHECK_NAME - 21/21 acceptance checks green"
  exit 0
else
  echo "FAIL: $CHECK_NAME - demo-check.sh reported failures (run it directly for detail)"
  exit 1
fi
