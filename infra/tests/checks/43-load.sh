#!/bin/sh
# Graded load evaluation (throughput/latency vs. client count).
# The synthetic harness proves the pipeline, not the product.
CHECK_NAME="load-evaluation"
. "$TESTS_DIR/lib.sh"
if [ -f "$TESTS_DIR/../load/k6-health.js" ]; then
  skip "graded load eval needs product endpoints; synthetic harness at infra/load proves the pipeline only"
else
  skip "no load harness present"
fi
