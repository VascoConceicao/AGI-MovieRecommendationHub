# Production image for the Angular frontend: Node 24 build, nginx runtime.
# The development server (ng serve) is never used here.
# Build from the repository root:
#   docker build -f app/frontend/Dockerfile -t g15-frontend:local .
FROM node:24-bookworm-slim AS build

WORKDIR /src

COPY app/frontend/package.json app/frontend/package-lock.json ./
RUN npm ci

COPY app/frontend ./
RUN npm run build

FROM nginx:1.28-alpine

COPY app/frontend/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /src/dist/frontend/browser /usr/share/nginx/html

EXPOSE 80
