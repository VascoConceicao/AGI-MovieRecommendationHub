#!/bin/sh
set -eu
repository_root=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
case "${1:-}" in
    movie|recommendation|user) exec "$repository_root/app/backend/$1-service/scripts/development/run.sh" ;;
    *) echo "Usage: $0 {movie|recommendation|user}" >&2; exit 2 ;;
esac
