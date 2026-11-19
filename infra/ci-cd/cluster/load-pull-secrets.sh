#!/bin/sh
# RUN BY THE PROJECT OWNER. Creates/updates the two registry PULL secrets from ONE read_registry-only deploy token:
#   g15-cd/gitlab-registry-read  (lets the deploy runner pull the ci-tools image)
#   g15-app/gitlab-registry      (lets the kubelet pull the application images by digest)
# Username and token are typed at HIDDEN prompts, travel only over SSH stdin and `kubectl ... --from-file=/dev/stdin`; they are never an
# argument, a file, an environment variable of a visible process, history, Git, a log or chat. Re-running rotates the credential.
set -eu
python3 -c '
import base64, getpass, json, sys
u = getpass.getpass("read_registry deploy-token USERNAME (e.g. gitlab+deploy-token-N, input hidden): ").strip()
t = getpass.getpass("read_registry deploy-token (input hidden): ").strip()
if not u or not t or any(c.isspace() for c in u + t):
    sys.exit(0)                                   # prints nothing: the remote side refuses an empty payload
sys.stdout.write(json.dumps({"auths": {"registry.rnl.tecnico.ulisboa.pt": {"username": u, "password": t, "auth": base64.b64encode((u + ":" + t).encode()).decode()}}}))
' |
gcloud compute ssh g15-cp1 --zone=europe-southwest1-a --project=prefab-conquest-511709-j5 --command '
  T=$(cat); case "$T" in "{\"auths\""*) ;; *) echo "ERROR: empty or invalid input; nothing created" >&2; exit 1;; esac
  K="sudo kubectl --kubeconfig=/etc/kubernetes/admin.conf"
  for spec in g15-cd:gitlab-registry-read g15-app:gitlab-registry; do
    ns=${spec%%:*}; name=${spec##*:}
    printf "%s" "$T" | $K -n $ns create secret generic $name --type=kubernetes.io/dockerconfigjson --from-file=.dockerconfigjson=/dev/stdin --dry-run=client -o yaml | $K apply -f - >/dev/null || exit 1
    $K -n $ns get secret $name --no-headers | awk -v n="$ns" "{print \"ready: \" n \"/\" \$1 \"  type=\" \$2 \"  keys=\" \$3}"
  done'
