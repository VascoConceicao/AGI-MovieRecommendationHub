#!/bin/sh
set -eu
# Initialize the first schema transactionally before accepting account requests.
python -m flask --app main:create_app init-db
exec gunicorn 'main:create_app()' --bind 0.0.0.0:4208 --workers 1 --threads 32
