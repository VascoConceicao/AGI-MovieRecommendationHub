#!/bin/sh
set -eu
component_root=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
if [ -f "$component_root/.env" ]; then
    . "$component_root/.env"
fi
: "${DATABASE_URL:=postgresql://movie:${MOVIE_DB_PASSWORD:?Set MOVIE_DB_PASSWORD or DATABASE_URL}@127.0.0.1:${MOVIE_DB_PORT:-5433}/movie}"
export DATABASE_URL
: "${MOVIE_WRITE_TOKEN:=}"
: "${MOVIE_RESET_ENABLED:=false}"
: "${MOVIE_RESET_TOKEN:=}"
: "${USER_SERVICE_URL:=http://127.0.0.1:4208}"
: "${WATCHED_CLEANUP_TOKEN:=}"
export MOVIE_WRITE_TOKEN MOVIE_RESET_ENABLED MOVIE_RESET_TOKEN USER_SERVICE_URL WATCHED_CLEANUP_TOKEN
if [ -n "${MOVIE_MEDIA_DIR:-}" ]; then export MOVIE_MEDIA_DIR; fi
if [ ! -x "$component_root/.venv/bin/python" ]; then
    echo "Install this service's .venv using the root README." >&2
    exit 1
fi
cd "$component_root"
.venv/bin/python -m flask --app main:create_app init-db
exec .venv/bin/python -m flask --app main:create_app run --host 127.0.0.1 --port 4206
