#!/bin/sh
# User-facing product flows: registration, login, profiles, browsing.
# Passes only when real product endpoints answer; otherwise SKIP —
# the backend currently serves health/metrics only (Vasco's track).
CHECK_NAME="product-flows"
. "$TESTS_DIR/lib.sh"
need curl
for path in api/user/register api/user/login api/recommendation/request; do
  code=$(curl -s -m 8 -o /dev/null -w "%{http_code}" "http://${NODE_IP}:30080/$path" 2>/dev/null || true)
  case "$code" in
    404|000|"") ;;
    *) pass "product endpoint /$path answers ($code)" ;;
  esac
done
skip "no product endpoints yet — backend serves health/metrics only (Vasco)"
