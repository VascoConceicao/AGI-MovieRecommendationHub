#!/bin/sh
set -eu
component_root=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
runtime="$component_root/.runtime"
if command -v nginx >/dev/null 2>&1; then
    nginx_binary=$(command -v nginx)
elif [ -x "$runtime/usr/sbin/nginx" ]; then
    nginx_binary="$runtime/usr/sbin/nginx"
else
    echo "Install Nginx with sudo apt install nginx, or run this component's scripts/setup/install.sh." >&2
    exit 1
fi
mkdir -p "$runtime/logs" "$runtime/client_temp" "$runtime/proxy_temp"
echo "Checking local Nginx configuration"
"$nginx_binary" -t -c "$component_root/nginx.local.conf" -p "$runtime/" -e stderr
exec "$nginx_binary" -c "$component_root/nginx.local.conf" -p "$runtime/" -e stderr -g "daemon off;"
