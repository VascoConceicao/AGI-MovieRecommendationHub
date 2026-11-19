#!/bin/sh
set -eu

if [ "$#" -lt 3 ] || [ "$#" -gt 4 ]; then
    echo "Usage: sh app/backend/common/scripts/ingestion/ingest-all.sh MOVIES USERS MAX_WATCHED [MAX_WATCHLIST]" >&2
    exit 2
fi
for count in "$@"; do
    case "$count" in
        ''|*[!0-9]*) echo "Counts must be whole numbers." >&2; exit 2 ;;
    esac
done
if ! [ "$1" -ge 1 ] || ! [ "$1" -le 10000 ] || ! [ "$2" -ge 1 ] || ! [ "$3" -ge 0 ]; then
    echo "Movies: 1–10000. Users: at least 1. Max watched: at least 0." >&2
    exit 2
fi

repository_root=$(CDPATH= cd -- "$(dirname -- "$0")/../../../../.." && pwd)
sh "$repository_root/app/backend/movie-service/db/ingestion/movies.sh" --count "$1"
exec sh "$repository_root/app/backend/user-service/db/ingestion/users.sh" --count "$2" --max-watched "$3" --max-watchlist "${4:-10}"
