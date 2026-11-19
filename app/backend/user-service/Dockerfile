# Production image for the user service.
# Build from the repository root so app/backend/common is in context:
#   docker build -f app/backend/user-service/Dockerfile -t g15-user-service:local .
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /srv/user-service

COPY app/backend/user-service/requirements.lock ./
RUN pip install --no-cache-dir -r requirements.lock gunicorn==23.0.0

COPY app/backend/common /common
RUN pip install --no-cache-dir /common

COPY app/backend/user-service/main.py ./
COPY app/backend/user-service/api ./api
COPY app/backend/user-service/helpers ./helpers
COPY app/backend/user-service/services ./services
COPY app/backend/user-service/db/sql ./db/sql
COPY app/backend/user-service/static ./static
COPY app/backend/user-service/db/migrations ./db/migrations
COPY app/backend/user-service/scripts/development/start.sh ./scripts/development/start.sh

EXPOSE 4208

CMD ["sh", "scripts/development/start.sh"]
