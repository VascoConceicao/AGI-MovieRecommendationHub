#!/bin/sh
set -eu
service_root=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
repo_root=$(CDPATH= cd -- "$service_root/../../.." && pwd)
exec python3 "$repo_root/scripts/testing/test_component.py" recommendation "$@"
