# Production image for the movie service.
# Build from the repository root so app/backend/common is in context:
#   docker build -f app/backend/movie-service/Dockerfile -t g15-movie-service:local .
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /srv/movie-service

COPY app/backend/movie-service/requirements.lock ./
RUN pip install --no-cache-dir -r requirements.lock gunicorn==23.0.0

COPY app/backend/common /common
RUN pip install --no-cache-dir /common

COPY app/backend/movie-service/main.py ./
COPY app/backend/movie-service/api ./api
COPY app/backend/movie-service/helpers ./helpers
COPY app/backend/movie-service/services ./services
COPY app/backend/movie-service/db/sql ./db/sql
COPY app/backend/movie-service/db/migrations ./db/migrations
COPY app/backend/movie-service/static ./static

COPY app/backend/movie-service/scripts/development/start.sh ./scripts/development/start.sh

EXPOSE 4206

CMD ["sh", "scripts/development/start.sh"]
