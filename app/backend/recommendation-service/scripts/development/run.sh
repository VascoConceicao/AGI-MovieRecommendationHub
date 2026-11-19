#!/bin/sh
set -eu
component_root=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
if [ -f "$component_root/.env" ]; then
    . "$component_root/.env"
fi
: "${DATABASE_URL:=postgresql://recommendation:${RECOMMENDATION_DB_PASSWORD:?Set RECOMMENDATION_DB_PASSWORD or DATABASE_URL}@127.0.0.1:${RECOMMENDATION_DB_PORT:-5434}/recommendation}"
export DATABASE_URL
: "${MOVIE_SERVICE_URL:=http://127.0.0.1:4206}"
export MOVIE_SERVICE_URL
: "${USER_SERVICE_URL:=http://127.0.0.1:4208}"
: "${AGENT_CONTEXT_TOKEN:=}"
export USER_SERVICE_URL AGENT_CONTEXT_TOKEN
export RECOMMENDATION_API_TOKEN RECOMMENDATION_RESET_TOKEN RECOMMENDATION_RESET_ENABLED
if [ ! -x "$component_root/.venv/bin/python" ]; then
    echo "Install this service's .venv using the root README." >&2
    exit 1
fi
cd "$component_root"
.venv/bin/python -m flask --app main:create_app init-db
exec .venv/bin/python -m flask --app main:create_app run --host 127.0.0.1 --port 4207
