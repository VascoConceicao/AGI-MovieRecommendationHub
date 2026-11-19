#!/bin/sh
set -eu
component_root=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
runtime="$component_root/.runtime"
mkdir -p "$runtime/packages" "$runtime/apt-lists/partial"
apt-get -o Dir::State::lists="$runtime/apt-lists" -o APT::Get::List-Cleanup=0 update
cd "$runtime/packages"
apt-get -o Dir::State::lists="$runtime/apt-lists" download nginx
for package in ./nginx_*.deb; do
    dpkg-deb -x "$package" "$runtime"
done
"$runtime/usr/sbin/nginx" -v
