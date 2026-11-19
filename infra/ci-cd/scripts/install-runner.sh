#!/bin/sh
set -eu
repo_root=$(CDPATH= cd -- "$(dirname -- "$0")/../../.." && pwd)
KUBECONFIG=${KUBECONFIG:-$repo_root/infra/terraform/cluster-gcp/kubeconfig.out}
export KUBECONFIG
env_file=${1:-$repo_root/infra/ci-cd/.env}
if [ ! -s "$env_file" ]; then
  echo "Set GITLAB_RUNNER_TOKEN in $env_file first." >&2
  exit 1
fi
chmod 600 "$env_file"
umask 077
token_dir=$(mktemp -d)
trap 'rm -rf "$token_dir"' EXIT HUP INT TERM
python3 - "$env_file" "$token_dir/runner-token" <<'PY'
from pathlib import Path
import sys

# Read the value as data; never execute .env contents as shell commands.
values = []
for line in Path(sys.argv[1]).read_text().splitlines():
    key, separator, value = line.strip().partition('=')
    if separator and key.strip() == 'GITLAB_RUNNER_TOKEN':
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values.append(value)
if (len(values) != 1 or not values[0].startswith('glrt-')
        or len(values[0]) <= 5 or any(c.isspace() for c in values[0])):
    sys.exit('Set one GITLAB_RUNNER_TOKEN=glrt-... value in the CI .env file.')
Path(sys.argv[2]).write_text(values[0])
PY
kubectl create namespace g15-ci --dry-run=client -o yaml | kubectl apply -f -
kubectl apply -f "$repo_root/infra/ci-cd/job-service-account.yaml"
# Token stays outside Git, shell arguments, and Helm release values.
kubectl -n g15-ci create secret generic gitlab-runner-token \
  --from-file=runner-token="$token_dir/runner-token" \
  --from-literal=runner-registration-token= \
  --dry-run=client -o yaml | kubectl apply -f -
helm upgrade --install gitlab-runner gitlab-runner \
  --repo https://charts.gitlab.io --version 0.94.0 \
  --namespace g15-ci --values "$repo_root/infra/ci-cd/runner-values.yaml" \
  --wait --timeout 5m
kubectl -n g15-ci rollout status deployment/gitlab-runner --timeout=120s
