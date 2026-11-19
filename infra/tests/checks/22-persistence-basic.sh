#!/bin/sh
# Pod-level persistence: every database owns a Bound PVC via
# volumeClaimTemplates. (Full-shutdown persistence is the open
# advanced track — see 60-advanced.)
CHECK_NAME="persistence-basic"
. "$TESTS_DIR/lib.sh"
need kubectl
n=$(kubectl -n g15-app get pvc --no-headers 2>/dev/null | awk '$2=="Bound"' | wc -l)
[ "$n" -ge 3 ] || fail "fewer than 3 Bound PVCs ($n)"
pass "$n Bound database PVCs via volumeClaimTemplates"
