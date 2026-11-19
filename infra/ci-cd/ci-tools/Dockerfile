# Deploy-job tools image: GitLab's Kubernetes executor needs a shell, and the official kubectl image has none.
# Built once with the validated Kaniko workflow and pinned by digest in values-deploy.yaml. Contains only what a deploy job needs.
FROM alpine:3.24.2@sha256:294b683cb724975bec92580e1e685676bd4b50bda910ddb8c51d4cabeaec77e6
RUN apk add --no-cache git curl jq ca-certificates
COPY --from=registry.k8s.io/kubectl@sha256:0667e3f3e6ef435d7cd4c16684244703ebd67314c17511c2a9f87ea44f6cdf6b /bin/kubectl /usr/local/bin/kubectl
RUN adduser -D -u 65532 cd
USER 65532
