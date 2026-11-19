#!/bin/sh
set -eu
repo_root=$(CDPATH= cd -- "$(dirname -- "$0")/../../.." && pwd)
cd "$repo_root"
case "${SUITE:-}" in
  scripts|common) component=app/backend/common ;;
  movie|recommendation|user) component="app/backend/$SUITE-service" ;;
  *) echo 'Set SUITE to scripts, common, movie, recommendation, or user.' >&2; exit 1 ;;
esac
python -m venv "$component/.venv"
"$component/.venv/bin/python" -m pip install -r "$component/requirements-test.lock"
"$component/.venv/bin/python" -m pip install -e app/backend/common
exec python scripts/testing/test_component.py "$SUITE"
