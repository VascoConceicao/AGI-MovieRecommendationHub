#!/bin/sh
set -eu
scripts_root=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
exec python3 "$scripts_root/test_component.py" common "$@"
