#!/bin/sh
# Regression test for the first real master dry-run failure ("'origin' does not appear to be a git repository").
# The runner's helper container creates the checkout as root; deploy.sh runs as uid 65532 in the ci-tools image. Git refuses to read a
# repository owned by someone else, and reports even a valid remote as "not a git repository". Needs docker; changes nothing else.
#   usage (repository root):  sh infra/ci-cd/tests/git-ownership-e2e.sh
set -eu
here=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd); root=$(CDPATH= cd -- "$here/../../.." && pwd)
T=$(mktemp -d); chmod a+rx "$T"; cp "$root/infra/ci-cd/scripts/deploy.sh" "$T/deploy.sh"; cp -r "$here/deploy-sim" "$T/sim"; chmod -R a+rX "$T"
ALP=alpine@sha256:294b683cb724975bec92580e1e685676bd4b50bda910ddb8c51d4cabeaec77e6
cat > "$T/run.sh" <<'IN'
apk add --no-cache git jq python3 >/dev/null 2>&1; adduser -D -u 65532 cd 2>/dev/null
git init -q --bare /w/bare.git; git clone -q /w/bare.git /w/repo 2>/dev/null; cd /w/repo
git config user.email a@b; git config user.name t; echo 1 > f; git add f; git commit -qm c1; git branch -M master; git push -q origin master
SHA=$(git rev-parse HEAD); mkdir -p published
for c in frontend proxy user-service movie-service recommendation-service ci-tools; do
  printf '{"component":"%s","repository":"registry.rnl.tecnico.ulisboa.pt/psia/groups26/g15/%s","tag":"sha-%s","digest":"sha256:%064d","commit":"%s"}\n' $c $c $SHA 1 $SHA > published/$c.json; done
python3 - <<'PY'
import json
cm=json.load(open('/w/sim/cd-state.fixture.json')); dep=json.loads(cm['data']['deployed.json']); leg={c:dep[c]['configDigest'] for c in dep if c!='recommendation-agent'}
dp={c:{'image':'g15-%s:local'%c,'pullPolicy':'Never','secrets':[]} for c in leg}; dp['inference']={'image':'x','gen':1,'rv':1}
json.dump({'cm':{'rv':1,'data':cm['data']},'deploy':dp,'legacy_cfg':leg,'cron':{'image':'g15-recommendation-service:local','pullPolicy':'Never','secrets':[],'suspend':False,'schedule':'*/3 * * * *','concurrencyPolicy':'Forbid','maxq':'4'}},open('/tmp/state.json','w'))
PY
chmod 666 /tmp/state.json; chmod -R a+rX /w
su cd -s /bin/sh -c "cd /w/repo
echo '[1] plain git as the job user:   '\$(git ls-remote origin refs/heads/master 2>&1 | head -1)
echo '[2] plain git rev-parse HEAD:    '\$(git rev-parse HEAD 2>&1 | head -1)
env HOME=/tmp SIM_STATE=/tmp/state.json PATH=/w/sim:\$PATH KUBECTL=/w/sim/kubectl CD_HEALTH=0 CI_PROJECT_DIR=/w/repo CI_REPOSITORY_URL=/w/bare.git CI_REGISTRY_IMAGE=registry.rnl.tecnico.ulisboa.pt/psia/groups26/g15 CI_COMMIT_SHA=$SHA CI_PIPELINE_ID=1 CI_PIPELINE_SOURCE=push CI_COMMIT_BRANCH=master CI_COMMIT_REF_PROTECTED=true sh /w/deploy.sh dry-run 2>&1 | tail -2"
IN
docker run --rm -v "$T:/w" --entrypoint sh "$ALP" /w/run.sh
echo "(temporary directory $T can be deleted)"
