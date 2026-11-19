#!/bin/sh
# RUN BY THE PROJECT OWNER on their workstation, after creating the runner in the GitLab UI.
#   usage: sh load-runner-token.sh build|deploy
# The token is typed at a HIDDEN prompt, streamed over SSH stdin straight into `kubectl create secret ... --from-file=/dev/stdin`.
# It is never an argument, never an environment variable of a visible process, never written to a file, history, Git, chat or log.
set -eu
kind=${1:?build or deploy}; case "$kind" in build) ns=g15-build;; deploy) ns=g15-cd;; *) echo "build or deploy" >&2; exit 2;; esac
python3 -c 'import getpass,sys; t=getpass.getpass("New %s runner token (glrt-..., input hidden): " % sys.argv[1]); sys.stdout.write(t if t.startswith("glrt-") and len(t) > 12 and not any(c.isspace() for c in t) else "")' "$kind" |
gcloud compute ssh g15-cp1 --zone=europe-southwest1-a --project=prefab-conquest-511709-j5 --command "
  T=\$(cat); case \"\$T\" in glrt-*) ;; *) echo 'ERROR: not a runner token; nothing created' >&2; exit 1;; esac
  printf '%s' \"\$T\" | sudo kubectl --kubeconfig=/etc/kubernetes/admin.conf -n $ns create secret generic gitlab-runner-token --from-file=runner-token=/dev/stdin --from-literal=runner-registration-token="
