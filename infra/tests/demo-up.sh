#!/bin/sh
# Bring up the local platform VMs (if stopped), wait for SSH, then run
# the acceptance gate. Companion to demo-check.sh: this script changes
# state (starts machines), demo-check.sh only asserts it.
#
# Usage (repository root):
#   sh infra/tests/demo-up.sh
# Environment defaults sensibly (see demo-check.sh); export to override.
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)

# Sensible defaults; override by exporting beforehand (inherited by the gate).
: "${KUBECONFIG:=$SCRIPT_DIR/../terraform/cluster/kubeconfig.out}"
: "${NODE_IP:=10.42.42.222}"
export KUBECONFIG NODE_IP
export TF_VAR_ssh_public_key="${TF_VAR_ssh_public_key:-$(cat ~/.ssh/id_ed25519.pub 2>/dev/null || true)}"

if docker ps -a --format '{{.Names}}' 2>/dev/null | grep -q '^g15-registry$'; then
  if docker ps --format '{{.Names}}' 2>/dev/null | grep -q '^g15-registry$'; then
    echo "g15-registry already running"
  else
    echo "starting g15-registry"
    docker start g15-registry >/dev/null
  fi
else
  echo "WARNING: g15-registry container missing (needed only for image distribution)"
fi

virsh -c qemu:///system net-start g15 >/dev/null 2>&1 || true

for vm in g15-cp1 g15-worker1 g15-worker2; do
  if [ "$(virsh -c qemu:///system domstate "$vm" 2>/dev/null)" = "shut off" ]; then
    echo "starting $vm"
    virsh -c qemu:///system start "$vm" >/dev/null
  else
    echo "$vm already running"
  fi
done

for ip in 10.42.42.222 10.42.42.185 10.42.42.247; do
  echo "waiting for SSH on $ip"
  timeout 600 sh -c "until ssh -q -o StrictHostKeyChecking=no -o ConnectTimeout=5 -i ~/.ssh/id_ed25519 ubuntu@$ip true 2>/dev/null; do sleep 10; done"
done

echo "waiting for API server (SSH up does not imply API up)"
timeout 600 sh -c "until curl -sk -m 5 https://$NODE_IP:6443/healthz >/dev/null 2>&1; do sleep 10; done"
echo "waiting for all nodes Ready"
kubectl --kubeconfig="$KUBECONFIG" wait --for=condition=Ready nodes --all --timeout=600s

exec sh "$SCRIPT_DIR/demo-check.sh"
