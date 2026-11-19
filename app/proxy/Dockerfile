# Production image for the Nginx reverse proxy.
# Same routing architecture as the local setup, with Kubernetes
# Service names instead of localhost ports. Build from the repo root:
#   docker build -f app/proxy/Dockerfile -t g15-proxy:local .
FROM nginx:1.28-alpine

COPY app/proxy/nginx.k8s.conf /etc/nginx/nginx.conf

EXPOSE 80
