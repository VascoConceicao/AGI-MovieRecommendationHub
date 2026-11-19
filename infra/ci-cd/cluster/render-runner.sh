#!/bin/sh
# Renders the (pinned) GitLab Runner chart to plain manifests on stdout. Needs only docker; contacts no cluster; contains no secret.
#   usage: sh render-runner.sh build|deploy
set -eu
kind=${1:?build or deploy}; case "$kind" in build) ns=g15-build;; deploy) ns=g15-cd;; *) echo "build or deploy" >&2; exit 2;; esac
here=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
exec docker run --rm -v "$here:/v:ro" alpine/helm:3.17.3 template "gitlab-runner-$kind" gitlab-runner \
  --repo https://charts.gitlab.io --version 0.94.0 --namespace "$ns" -f "/v/values-$kind.yaml"
