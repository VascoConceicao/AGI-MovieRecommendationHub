# Production image for the recommendation service.
# Build from the repository root so app/backend/common is in context:
#   docker build -f app/backend/recommendation-service/Dockerfile -t g15-recommendation-service:local .
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /srv/recommendation-service

COPY app/backend/recommendation-service/requirements.lock ./
RUN pip install --no-cache-dir -r requirements.lock gunicorn==23.0.0

COPY app/backend/common /common
RUN pip install --no-cache-dir /common

COPY app/backend/recommendation-service/main.py ./
COPY app/backend/recommendation-service/api ./api
COPY app/backend/recommendation-service/helpers ./helpers
COPY app/backend/recommendation-service/services ./services
COPY app/backend/recommendation-service/db/sql ./db/sql
COPY app/backend/recommendation-service/db/migrations ./db/migrations
COPY app/backend/recommendation-service/scripts/development/start.sh ./scripts/development/start.sh
COPY app/backend/recommendation-service/static ./static

EXPOSE 4207

CMD ["sh", "scripts/development/start.sh"]
