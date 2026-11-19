#!/bin/sh
# Full stop of the local demo platform: VMs (graceful, with fallback)
# then the image registry. Companion to demo-up.sh.
#
# Usage (repository root):
#   sh infra/tests/demo-stop.sh
set -eu

echo "== pre-stop host RAM:"
free -h | head -n 2
echo "== pre-stop domains:"
virsh -c qemu:///system list --all

for vm in g15-cp1 g15-worker1 g15-worker2; do
  state=$(virsh -c qemu:///system domstate "$vm" 2>/dev/null || echo missing)
  if [ "$state" = "running" ]; then
    echo "stopping $vm (graceful shutdown)"
    virsh -c qemu:///system shutdown "$vm" >/dev/null
    waited=0
    while [ "$(virsh -c qemu:///system domstate "$vm" 2>/dev/null)" = "running" ] && [ "$waited" -lt 120 ]; do
      sleep 10
      waited=$((waited + 10))
    done
    state=$(virsh -c qemu:///system domstate "$vm" 2>/dev/null || echo missing)
    if [ "$state" = "running" ]; then
      echo "WARNING: $vm did not stop in 120s, forcing power off"
      virsh -c qemu:///system destroy "$vm" >/dev/null
    else
      echo "$vm is $state"
    fi
  else
    echo "$vm already $state, skipping"
  fi
done

if docker ps --format '{{.Names}}' 2>/dev/null | grep -q '^g15-registry$'; then
  echo "stopping g15-registry"
  docker stop g15-registry >/dev/null
else
  echo "g15-registry not running, skipping"
fi

echo "== post-stop domains:"
virsh -c qemu:///system list --all
echo "== post-stop host RAM:"
free -h | head -n 2
