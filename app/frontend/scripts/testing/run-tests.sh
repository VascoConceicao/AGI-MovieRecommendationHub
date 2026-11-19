#!/bin/sh
set -eu
frontend_root=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
repo_root=$(CDPATH= cd -- "$frontend_root/../.." && pwd)
exec python3 "$repo_root/scripts/testing/test_component.py" frontend "$@"
