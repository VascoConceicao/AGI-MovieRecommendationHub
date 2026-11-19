#!/bin/sh
set -u
repository_root=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
result=0
for component in proxy frontend movie recommendation user; do
    python3 "$repository_root/scripts/development/manage-component.py" stop "$component" || result=1
done
cd "$repository_root" || exit 1
docker compose stop movie-db recommendation-db user-db || result=1
exit "$result"
