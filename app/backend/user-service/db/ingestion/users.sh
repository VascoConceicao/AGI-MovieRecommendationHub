#!/bin/sh
set -eu
service_root=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
if [ -f "$service_root/.env" ]; then
    . "$service_root/.env"
fi
: "${DATABASE_URL:?Set DATABASE_URL in user-service/.env}"
: "${MOVIE_SERVICE_URL:=http://127.0.0.1:4206}"
export DATABASE_URL MOVIE_SERVICE_URL
exec "$service_root/.venv/bin/python" "$service_root/db/ingestion/users.py" "$@"
