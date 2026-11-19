#!/bin/sh
set -eu
component_root=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
if [ -f "$component_root/.env" ]; then
    . "$component_root/.env"
fi
: "${DATABASE_URL:=postgresql://users:${USER_DB_PASSWORD:?Set USER_DB_PASSWORD or DATABASE_URL}@127.0.0.1:${USER_DB_PORT:-5435}/users}"
export DATABASE_URL
: "${AUTH_COOKIE_SECURE:=false}"
export AUTH_COOKIE_SECURE
# Export optional reset settings read from this service's .env file.
: "${AUTH_RESET_ENABLED:=false}"
: "${AUTH_RESET_TOKEN:=}"
: "${WATCHED_CLEANUP_TOKEN:=}"
: "${MOVIE_SERVICE_URL:=http://127.0.0.1:4206}"
export AUTH_RESET_ENABLED AUTH_RESET_TOKEN WATCHED_CLEANUP_TOKEN MOVIE_SERVICE_URL
: "${RECOMMENDATION_SERVICE_URL:=http://127.0.0.1:4207}"
: "${RECOMMENDATION_API_TOKEN:=}"
export RECOMMENDATION_SERVICE_URL RECOMMENDATION_API_TOKEN
: "${AGENT_CONTEXT_TOKEN:=}"
export AGENT_CONTEXT_TOKEN
if [ ! -x "$component_root/.venv/bin/python" ]; then
    echo "Install this service's .venv using the root README." >&2
    exit 1
fi
cd "$component_root"
.venv/bin/python -m flask --app main:create_app init-db
exec .venv/bin/python -m flask --app main:create_app run --host 127.0.0.1 --port 4208
