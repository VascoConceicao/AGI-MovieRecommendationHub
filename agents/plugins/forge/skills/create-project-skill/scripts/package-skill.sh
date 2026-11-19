#!/bin/sh
set -eu
# Validate package membership using the installed resource directory.
script_directory=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
exec python3 "$script_directory/plugin-skill.py" "$@"
