#!/bin/sh
set -eu
python -m flask --app main:create_app init-db
exec gunicorn 'main:create_app()' --bind 0.0.0.0:4207 --workers 1 --threads 4
