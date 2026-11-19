#!/bin/sh
set -eu
component_root=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
exec sh "$component_root/scripts/with-node.sh" npm start
