#!/bin/sh
set -eu
service_root=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
if [ -f "$service_root/.env" ]; then
    set -a
    . "$service_root/.env"
    set +a
fi
exec "$service_root/.venv/bin/python" "$service_root/db/ingestion/movies.py" "$@"
