#!/bin/sh
set -eu
component_root=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
case "${1:-}" in
    '') recreate=--force-recreate ;;
    --ensure) recreate=--no-recreate ;;
    *) echo "Usage: $0 [--ensure]" >&2; exit 2 ;;
esac
exec docker compose --env-file "$component_root/.env" -f "$component_root/db/compose.yaml" \
    up --detach "$recreate" --wait --wait-timeout 60 --no-deps user-db
