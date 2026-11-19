#!/bin/sh
set -eu
repo_root=$(CDPATH= cd -- "$(dirname -- "$0")/../../.." && pwd)
cd "$repo_root"
# Keep Angular build workers limited while CI shares nodes with the app.
NG_BUILD_MAX_WORKERS=1
VITEST_MAX_WORKERS=1
export NG_BUILD_MAX_WORKERS VITEST_MAX_WORKERS
sh app/frontend/scripts/with-node.sh npm ci --include=dev --no-audit --no-fund
exec sh app/frontend/scripts/with-node.sh npm exec -- ng test \
  --watch=false --coverage --progress=false \
  --runner-config=../../infra/ci-cd/vitest.config.mjs
