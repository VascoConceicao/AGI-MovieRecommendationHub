#!/bin/sh
# Guarded Terraform apply: exactly one Terraform process at a time,
# state snapshot before, state sanity check after.
#
# Usage (repository root):
#   sh infra/terraform/tf-apply.sh infra/terraform/app [terraform args...]
# Environment (TF_DATA_DIR, TF_VAR_*) passes through untouched.
#
# Background: two unexplained empty-state incidents both correlate with
# overlapping Terraform executions from timed-out shells. Until that
# hypothesis is disproven, overlapping runs are refused outright.
set -eu

LOCK=/tmp/g15-terraform.lock
BACKUP_ROOT=/tmp/opencode/tfstate-backups

if [ "$#" -lt 1 ]; then
  echo "usage: $0 <layer-dir> [terraform apply args...]" >&2
  exit 2
fi

LAYER=$1
shift

STATE_DIR=${TF_DATA_DIR:-$LAYER}
STAMP=$(date +%Y%m%d-%H%M%S)-$(basename "$LAYER")
BACKUP_DIR="$BACKUP_ROOT/$STAMP"

exec 9>"$LOCK"
if ! flock -n 9; then
  echo "refusing: another Terraform run holds $LOCK" >&2
  exit 1
fi

mkdir -p "$BACKUP_DIR"
pre_count=0
for f in "$STATE_DIR"/terraform.tfstate; do
  if [ -f "$f" ]; then
    cp "$f" "$BACKUP_DIR/"
    pre_count=$(python3 -c "import json;print(len(json.load(open('$f')).get('resources',[])))" 2>/dev/null || echo 0)
  fi
done
echo "state backup: $BACKUP_DIR (resources before: $pre_count)"

terraform -chdir="$LAYER" apply "$@"

post_count=$(python3 -c "import json;print(len(json.load(open('$STATE_DIR/terraform.tfstate')).get('resources',[])))")
echo "resources before: $pre_count, after: $post_count"
if [ "$post_count" -eq 0 ] && [ "$pre_count" -gt 0 ]; then
  echo "refusing to accept empty state: restore from $BACKUP_DIR and investigate" >&2
  exit 1
fi
