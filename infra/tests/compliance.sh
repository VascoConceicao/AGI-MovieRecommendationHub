#!/bin/sh
# Compliance battery: maps project requirements to executable checks.
# Each check prints one line and exits: 0=PASS, 2=SKIP (with reason),
# anything else=FAIL. Skips never block: unimplemented tracks exist as
# checks so gaps are visible, not forgotten.
#
# Usage (repository root):
#   sh infra/tests/compliance.sh
# Optional: GCE_KUBECONFIG=<path> enables the public-cloud checks.
set -eu

TESTS_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
export TESTS_DIR

: "${KUBECONFIG:=$TESTS_DIR/../terraform/cluster/kubeconfig.out}"
: "${NODE_IP:=10.42.42.222}"
export KUBECONFIG NODE_IP
export TF_VAR_ssh_public_key="${TF_VAR_ssh_public_key:-$(cat ~/.ssh/id_ed25519.pub 2>/dev/null || true)}"

PASS=0
FAIL=0
SKIPPED=0
FAILED_LIST=""

for check in "$TESTS_DIR"/checks/*.sh; do
  name=$(basename "$check" .sh)
  if out=$(timeout 180 sh "$check" 2>&1); then
    PASS=$((PASS + 1))
    echo "$out"
  else
    rc=$?
    if [ "$rc" -eq 2 ]; then
      SKIPPED=$((SKIPPED + 1))
      echo "$out"
    else
      FAIL=$((FAIL + 1))
      echo "$out"
      FAILED_LIST="$FAILED_LIST $name"
    fi
  fi
done

echo "---"
echo "pass=$PASS fail=$FAIL skipped=$SKIPPED"
[ "$FAIL" -eq 0 ] || { echo "failed:$FAILED_LIST"; exit 1; }
