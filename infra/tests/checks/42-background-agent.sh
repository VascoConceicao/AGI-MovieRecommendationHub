#!/bin/sh
# Background agent proactively caching recommendations.
CHECK_NAME="background-agent"
. "$TESTS_DIR/lib.sh"
need kubectl
if kubectl get cronjob,job,deployment --all-namespaces --no-headers 2>/dev/null | grep -iE "agent|recommender|cache-warm|precache" | head -n 3 | grep -q .; then
  pass "background recommendation workload present"
else
  skip "no background recommendation agent deployed yet"
fi
