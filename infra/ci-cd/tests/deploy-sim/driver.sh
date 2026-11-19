#!/bin/bash
# usage: driver.sh   (inside the test container)  -- every scenario gets a fresh state and fresh git repos
export SIM_STATE=/tmp/state.json PATH=/sim:$PATH; REG=registry.rnl.tecnico.ulisboa.pt/psia/groups26/g15
PASS=0; FAILN=0; N=0
ok() { if eval "$2"; then PASS=$((PASS+1)); echo "    ok    $1"; else FAILN=$((FAILN+1)); echo "    FAIL  $1"; [ -n "${SHOWLOG:-}" ] && { echo "      ---- script log (rc=$RC) ----"; tail -14 /tmp/out.txt | sed "s/^/      /"; }; fi; }
st() { X="$1" python3 -c 'import json,os; s=json.load(open("/tmp/state.json")); print(eval(os.environ["X"]))'; }
newscenario() { N=$((N+1)); echo; echo "### S$N  $1"; D=$(mktemp -d); O=$D/o.git; W=$D/w; git init -q --bare $O; git clone -q $O $W 2>/dev/null; cd $W; git config user.email t@t; git config user.name t; git checkout -q -b master; echo published >> .git/info/exclude
  for d in app/frontend app/proxy app/backend/user-service app/backend/movie-service app/backend/recommendation-service app/backend/common; do mkdir -p $d; echo v1 > $d/f; done; git add -A; git commit -qm c1; git push -q $O master 2>/dev/null; git remote remove origin
  python3 - <<'PY'
import json
cm=json.load(open('/m5/cd-state.json')); dep=json.loads(cm['data']['deployed.json'])
leg={c:dep[c]['configDigest'] for c in dep if c!='recommendation-agent'}
deploy={c:{'image':'g15-%s:local'%c,'pullPolicy':'Never','secrets':[]} for c in leg}; deploy['inference']={'image':'ghcr.io/x/llama@sha256:'+'a'*64,'gen':1,'rv':70922}
json.dump({'cm':{'rv':100,'data':cm['data']},'deploy':deploy,'legacy_cfg':leg,'cron':{'image':'g15-recommendation-service:local','pullPolicy':'Never','secrets':[],'suspend':False,'schedule':'*/3 * * * *','concurrencyPolicy':'Forbid','maxq':'4'}},open('/tmp/state.json','w'))
PY
}
publish() { cd $W; sha=$(git rev-parse HEAD); mkdir -p published; for c in frontend proxy user-service movie-service recommendation-service ci-tools; do
  printf '{"component":"%s","repository":"%s/%s","tag":"sha-%s","digest":"sha256:%064d","commit":"%s"}\n' $c $REG $c $sha $((RANDOM*32768+RANDOM)) $sha > published/$c.json; done; }
change() { cd $W; echo $RANDOM >> $1/f; git add -A; git commit -qm change; git push -q $O master 2>/dev/null; }
run() { m=$1; shift; ( cd $W; env KUBECTL=/sim/kubectl CD_HEALTH=${HEALTH:-0} CD_HEALTH_PROXY=http://proxy.g15-app.svc.cluster.local CI_REGISTRY_IMAGE=$REG CI_REPOSITORY_URL=$O CI_COMMIT_SHA=$(git rev-parse HEAD) CI_PIPELINE_ID=${PID:-1} CI_PIPELINE_SOURCE=${SRC:-push} CI_COMMIT_BRANCH=${BR:-master} CI_COMMIT_REF_PROTECTED=${PROT:-true} "$@" sh /deploy.sh $m ) > /tmp/out.txt 2>&1; RC=$?; }
has() { grep -q -- "$1" /tmp/out.txt; }
img() { st "s['deploy']['$1']['image']"; }
allegacy() { for c in frontend proxy user-service movie-service recommendation-service; do case "$(img $c)" in g15-*:local) ;; *) return 1;; esac; done; [ "$(st "s['cron']['image']")" = g15-recommendation-service:local ]; }
patches() { st "s.get('patch_count',0)"; }

newscenario "smoke: identity, RBAC, admission accept/reject, state, invariants"; BR=development run smoke; ok "exit 0 and SMOKE OK" '[ $RC -eq 0 ] && has "SMOKE OK"'; ok "admission rejection of a foreign image was checked" 'has "another component.s image is rejected"'; ok "nothing patched (dry-run only)" '[ "$(patches)" = 0 ]'
newscenario "dry-run on master changes nothing"; publish; run dry-run; ok "exit 0 / DRY-RUN OK" '[ $RC -eq 0 ] && has "DRY-RUN OK"'; ok "no patch, still legacy" '[ "$(patches)" = 0 ] && allegacy'; ok "state still idle" '[ "$(st "s[\"cm\"][\"data\"][\"status\"]")" = idle ]'
newscenario "first deploy: only the default component (frontend) migrates"; publish; run deploy; SHA=$(git -C $W rev-parse HEAD)
ok "exit 0, DEPLOYMENT VERIFIED" '[ $RC -eq 0 ] && has "DEPLOYMENT VERIFIED"'; ok "frontend now a registry digest + IfNotPresent + pull secret" '[[ "$(img frontend)" == $REG/frontend@sha256:* ]] && [ "$(st "s[\"deploy\"][\"frontend\"][\"pullPolicy\"]")" = IfNotPresent ] && [ "$(st "s[\"deploy\"][\"frontend\"][\"secrets\"][0][\"name\"]")" = gitlab-registry ]'
ok "other four still on the legacy images, CronJob untouched" '[ "$(img proxy)" = g15-proxy:local ] && [ "$(img user-service)" = g15-user-service:local ] && [ "$(img movie-service)" = g15-movie-service:local ] && [ "$(img recommendation-service)" = g15-recommendation-service:local ] && [ "$(st "s[\"cron\"][\"image\"]")" = g15-recommendation-service:local ]'
ok "state: idle, lastVerifiedCommit set, frontend recorded as registry" '[ "$(st "s[\"cm\"][\"data\"][\"status\"]")" = idle ] && [ "$(st "s[\"cm\"][\"data\"][\"lastVerifiedCommit\"]")" = "$SHA" ] && [ "$(st "__import__(\"json\").loads(s[\"cm\"][\"data\"][\"deployed.json\"])[\"frontend\"][\"kind\"]")" = registry ]'
ok "previous.json still holds the legacy frontend (rollback target)" '[ "$(st "__import__(\"json\").loads(s[\"cm\"][\"data\"][\"previous.json\"])[\"frontend\"][\"image\"]")" = g15-frontend:local ]'
ok "inference never touched" '[ "$(st "s[\"deploy\"][\"inference\"][\"rv\"]")" = 70922 ]'
run deploy; ok "re-running the same commit is a no-op" '[ $RC -eq 0 ] && has "already running the target image" && has "nothing to deploy"'
newscenario "all five at once: dependency order, CronJob follows recommendation, invariants preserved"; publish; run deploy DEPLOY_COMPONENTS=all
ok "exit 0" '[ $RC -eq 0 ]'; ok "all five on registry digests" '[[ "$(img frontend)" == $REG/frontend@* && "$(img proxy)" == $REG/proxy@* && "$(img user-service)" == $REG/user-service@* && "$(img movie-service)" == $REG/movie-service@* && "$(img recommendation-service)" == $REG/recommendation-service@* ]]'
ok "CronJob uses the SAME image as recommendation-service" '[ "$(st "s[\"cron\"][\"image\"]")" = "$(img recommendation-service)" ]'; ok "CronJob suspend/schedule/concurrency/AGENT_MAX_QUEUED unchanged" '[ "$(st "s[\"cron\"][\"suspend\"]")" = False ] && [ "$(st "s[\"cron\"][\"schedule\"]")" = "*/3 * * * *" ] && [ "$(st "s[\"cron\"][\"maxq\"]")" = 4 ]'
ok "deployed in dependency order (movie before user before recommendation before proxy before frontend)" 'o=$(grep -o "deploying [a-z-]*" /tmp/out.txt | awk "{print \$2}" | tr "\n" " "); [ "$o" = "movie-service user-service recommendation-service recommendation-agent proxy frontend " ]'
# selective deployment on later commits (state carries over)
change app/frontend; publish; run deploy DEPLOY_COMPONENTS=all; ok "frontend-only change: ONLY frontend restarts" '[ $RC -eq 0 ] && has "frontend: sources changed" && has "proxy: sources unchanged" && has "user-service: sources unchanged" && has "movie-service: sources unchanged" && has "recommendation-service: sources unchanged"'
change app/backend/common; publish; run deploy DEPLOY_COMPONENTS=all; ok "common change: three backends + CronJob redeploy, proxy/frontend skipped" '[ $RC -eq 0 ] && has "user-service: sources changed" && has "movie-service: sources changed" && has "recommendation-service: sources changed" && has "proxy: sources unchanged" && has "frontend: sources unchanged"'
newscenario "recommendation rollout fails -> automatic rollback of everything already touched"; publish; python3 - <<'PY'
import json; s=json.load(open('/tmp/state.json')); s['bad_new']=['recommendation-service']; json.dump(s,open('/tmp/state.json','w'))
PY
run deploy DEPLOY_COMPONENTS=all; ok "job fails" '[ $RC -ne 0 ]'; ok "rollback ran and was verified" 'has "ROLLBACK VERIFIED"'; ok "EVERY workload back on the legacy image (incl. CronJob)" 'allegacy'; ok "state idle, result says rolled back, lastVerifiedCommit untouched, deployed.json unchanged" '[ "$(st "s[\"cm\"][\"data\"][\"status\"]")" = idle ] && [[ "$(st "s[\"cm\"][\"data\"][\"lastResult\"]")" == *"rolled back"* ]] && [ -z "$(st "s[\"cm\"][\"data\"][\"lastVerifiedCommit\"]")" ] && [ "$(st "__import__(\"json\").loads(s[\"cm\"][\"data\"][\"deployed.json\"])[\"user-service\"][\"kind\"]")" = legacy ]'
newscenario "health check fails after a component rolls -> rollback"; publish; : > /tmp/hf; echo "4208/health" > /tmp/hf; HEALTH=1 run deploy DEPLOY_COMPONENTS=user-service SIM_HEALTH_FAIL=/tmp/hf; ok "job fails, rollback verified" '[ $RC -ne 0 ] && has "health check failed" && has "ROLLBACK VERIFIED"'; ok "user-service back on the legacy image" 'allegacy'
newscenario "admission policy denies a patch mid-run (proxy) -> earlier components rolled back"; publish; python3 - <<'PY'
import json; s=json.load(open('/tmp/state.json')); s['deny_patch']='proxy'; json.dump(s,open('/tmp/state.json','w'))
PY
run deploy DEPLOY_COMPONENTS=all; ok "job fails and rolls back" '[ $RC -ne 0 ] && has "ROLLBACK VERIFIED"'; ok "everything legacy again" 'allegacy'
newscenario "lock already held (in_progress) -> refuse, change nothing"; publish; python3 - <<'PY'
import json; s=json.load(open('/tmp/state.json')); s['cm']['data']['status']='in_progress'; json.dump(s,open('/tmp/state.json','w'))
PY
run deploy; ok "refused" '[ $RC -ne 0 ] && has "not idle"'; ok "nothing patched, state still in_progress for the human to review" '[ "$(patches)" = 0 ] && allegacy && [ "$(st "s[\"cm\"][\"data\"][\"status\"]")" = in_progress ]'
newscenario "rollback_failed state also blocks new deploys"; publish; python3 - <<'PY'
import json; s=json.load(open('/tmp/state.json')); s['cm']['data']['status']='rollback_failed'; json.dump(s,open('/tmp/state.json','w'))
PY
run deploy; ok "refused" '[ $RC -ne 0 ] && has "rollback_failed" && [ "$(patches)" = 0 ]'
newscenario "two pipelines race for the lock (CAS conflict) -> loser changes nothing"; publish; python3 - <<'PY'
import json; s=json.load(open('/tmp/state.json')); s['conflict_on_lock']=True; json.dump(s,open('/tmp/state.json','w'))
PY
run deploy; ok "loser stops at the lock" '[ $RC -ne 0 ] && has "could not take the lock"'; ok "no image changed, state untouched" '[ "$(patches)" = 0 ] && allegacy && [ "$(st "s[\"cm\"][\"data\"][\"status\"]")" = idle ]'
newscenario "stale pipeline (master moved on) -> superseded, exit 75, nothing changes"; publish; W2=$(mktemp -d); git clone -q $O $W2/c 2>/dev/null; ( cd $W2/c; git config user.email t@t; git config user.name t; echo x > newer; git add -A; git commit -qm newer; git push -q origin master ) 2>/dev/null
run deploy; ok "exit 75 SUPERSEDED" '[ $RC -eq 75 ] && has "SUPERSEDED"'; ok "no change" '[ "$(patches)" = 0 ] && allegacy'
newscenario "commit older than the last verified deployment -> refuse"; publish; ( cd $W; git checkout -q -b side; echo s > side; git add -A; git commit -qm side; git push -q $O side 2>/dev/null; git checkout -q master )
python3 - <<PY
import json,subprocess; side=subprocess.check_output(['git','-C','$W','rev-parse','side']).decode().strip()
s=json.load(open('/tmp/state.json')); s['cm']['data']['lastVerifiedCommit']=side; json.dump(s,open('/tmp/state.json','w'))
PY
run deploy; ok "refused (not a descendant of the last verified commit)" '[ $RC -ne 0 ] && has "older than the last verified"'; ok "no change" '[ "$(patches)" = 0 ]'
newscenario "deploy from a non-master / unprotected / MR source is refused"; publish; BR=development run deploy; ok "development refused" '[ $RC -ne 0 ] && has "only allowed from a push to the protected branch master"'; SRC=merge_request_event run deploy; ok "merge-request source refused" '[ $RC -ne 0 ]'; PROT=false run deploy; ok "unprotected ref refused" '[ $RC -ne 0 ]'; BR=development run rollback; ok "rollback job also refused off master" '[ $RC -ne 0 ]'; ok "nothing changed" '[ "$(patches)" = 0 ]'
newscenario "CronJob invariants broken (suspended) -> refuse BEFORE any change"; publish; python3 - <<'PY'
import json; s=json.load(open('/tmp/state.json')); s['cron']['suspend']=True; json.dump(s,open('/tmp/state.json','w'))
PY
run deploy DEPLOY_COMPONENTS=all; ok "refused up front" '[ $RC -ne 0 ] && has "CronJob invariants differ"'; ok "nothing patched" '[ "$(patches)" = 0 ]'
newscenario "Qwen (inference) changes while deploying -> rollback"; publish; python3 - <<'PY'
import json; s=json.load(open('/tmp/state.json')); s['inference_bump_after']=2; json.dump(s,open('/tmp/state.json','w'))
PY
run deploy DEPLOY_COMPONENTS=all; ok "job fails and rolls back" '[ $RC -ne 0 ] && has "inference Deployment changed" && has "ROLLBACK VERIFIED"'; ok "all legacy" 'allegacy'
newscenario "published artifact problems are rejected"; publish; rm_ok=1; mv $W/published/proxy.json $W/published/proxy.json.bak; run deploy; ok "missing publish result rejected" '[ $RC -ne 0 ] && has "missing published/proxy.json"'; mv $W/published/proxy.json.bak $W/published/proxy.json
sed -i 's/"commit":"[0-9a-f]*"/"commit":"0000000000000000000000000000000000000000"/' $W/published/frontend.json; run deploy; ok "artifact for another commit rejected" '[ $RC -ne 0 ] && has "does not describe frontend"'; ok "nothing patched" '[ "$(patches)" = 0 ]'
newscenario "manual rollback job restores the pre-deploy state"; publish; run deploy DEPLOY_COMPONENTS=all; ok "deployed" '[ $RC -eq 0 ]'; run rollback; ok "rollback job succeeds and verifies" '[ $RC -eq 0 ] && has "ROLLBACK VERIFIED"'; ok "everything back on the legacy images and state matches" 'allegacy && [ "$(st "__import__(\"json\").loads(s[\"cm\"][\"data\"][\"deployed.json\"])[\"frontend\"][\"kind\"]")" = legacy ] && [ "$(st "s[\"cm\"][\"data\"][\"status\"]")" = idle ]'; run rollback; ok "second rollback is a no-op" '[ $RC -eq 0 ] && has "nothing to roll back"'

bg() { # background deploy in its own process group (like a runner job); $1 = signal to send after $2 seconds; sets RC
  ( cd $W; exec setsid env KUBECTL=/sim/kubectl CD_HEALTH=${HEALTH:-0} CD_HEALTH_PROXY=http://proxy.g15-app.svc.cluster.local CI_REGISTRY_IMAGE=$REG CI_REPOSITORY_URL=$O CI_COMMIT_SHA=$(git rev-parse HEAD) CI_PIPELINE_ID=77 CI_PIPELINE_SOURCE=push CI_COMMIT_BRANCH=master CI_COMMIT_REF_PROTECTED=true DEPLOY_COMPONENTS=all "${@:3}" sh /deploy.sh deploy ) > /tmp/out.txt 2>&1 &
  pid=$!; /bin/sleep $2; kill -$1 -- -$pid 2>/dev/null; wait $pid 2>/dev/null; RC=$?; }
slowstate() { python3 - <<PY
import json; s=json.load(open('/tmp/state.json')); s['slow_rollout']=$1; json.dump(s,open('/tmp/state.json','w'))
PY
}
newscenario "job CANCEL / TIMEOUT (SIGTERM) in the middle of a rollout -> rollback runs and verifies"; publish; slowstate 6; bg TERM 3
ok "job ended by the signal" '[ $RC -ne 0 ]'; ok "rollback ran and was verified" 'has "ROLLBACK VERIFIED"'; ok "everything back on the legacy images, state idle" 'allegacy && [ "$(st "s[\"cm\"][\"data\"][\"status\"]")" = idle ]'
newscenario "HARD KILL (SIGKILL: pod/node lost) -> fail-closed, then the manual rollback job RECOVERS the orphaned lock"; publish; slowstate 6; bg KILL 3
ok "no rollback could run: state left in_progress" '[ "$(st "s[\"cm\"][\"data\"][\"status\"]")" = in_progress ]'
ok "production is on the new image for the interrupted component (this is the honest limitation)" '! allegacy'
run deploy DEPLOY_COMPONENTS=all; ok "a new deploy is REFUSED and points at the rollback job" '[ $RC -ne 0 ] && has "deploy:rollback"'
run rollback; ok "rollback job recovers the orphaned lock and restores production" '[ $RC -eq 0 ] && has "RECOVERY" && has "ROLLBACK VERIFIED"'; ok "all legacy, state idle again" 'allegacy && [ "$(st "s[\"cm\"][\"data\"][\"status\"]")" = idle ]'
newscenario "recovery rollback works even while production health is FAILING"; publish; slowstate 6; bg KILL 3; echo "api/user/health" > /tmp/hf2; HEALTH=1 run rollback SIM_HEALTH_FAIL=/tmp/hf2
ok "rollback does not demand health up front and ends healthy" '[ $RC -eq 0 ] && has "ROLLBACK VERIFIED" && allegacy'
newscenario "internal deadline: a slow deployment stops itself and rolls back while time remains"; publish; slowstate 2; run deploy DEPLOY_COMPONENTS=all CD_MAX_SECONDS=1
ok "deadline reached, rollback verified" '[ $RC -ne 0 ] && has "deadline of 1s reached" && has "ROLLBACK VERIFIED"'; ok "all legacy" 'allegacy'

newscenario "DRIFT: production changed outside CD (e.g. a rogue job or a manual kubectl) -> refuse to deploy over it"; publish; python3 - <<'PY'
import json; s=json.load(open('/tmp/state.json')); s['deploy']['proxy']['image']='registry.rnl.tecnico.ulisboa.pt/psia/groups26/g15/proxy@sha256:'+'e'*64; json.dump(s,open('/tmp/state.json','w'))
PY
run deploy DEPLOY_COMPONENTS=all; ok "deploy refused" '[ $RC -ne 0 ] && has "DRIFT: proxy" && has "drifted"'; ok "nothing patched" '[ "$(patches)" = 0 ]'; run dry-run; ok "dry-run also flags it" '[ $RC -ne 0 ] && has "DRIFT: proxy"'; BR=development run smoke; ok "smoke flags it too" '[ $RC -ne 0 ] && has "DRIFT: proxy"'
newscenario "no drift after a normal deploy -> the next deploy proceeds"; publish; run deploy DEPLOY_COMPONENTS=all; ok "first deploy ok" '[ $RC -eq 0 ]'; change app/frontend; publish; run deploy DEPLOY_COMPONENTS=all; ok "second deploy ok (live images match the record)" '[ $RC -eq 0 ] && ! has "DRIFT"'

newscenario "no git remote in the checkout (as in the failing job): the stale guard still works through CI_REPOSITORY_URL"; publish
ok "the test clone really has no 'origin' remote" '[ -z "$(git -C $W remote)" ]'; run dry-run; ok "dry-run on master passes without any remote name" '[ $RC -eq 0 ] && has "DRY-RUN OK"'
W2=$(mktemp -d); git clone -q $O $W2/c 2>/dev/null; ( cd $W2/c; git config user.email t@t; git config user.name t; echo x > newer; git add -A; git commit -qm newer; git push -q $O master ) 2>/dev/null
run deploy; ok "a newer master is still detected (exit 75 SUPERSEDED)" '[ $RC -eq 75 ] && has "SUPERSEDED"'
newscenario "stale guard FAILS CLOSED when the remote cannot be checked"; publish
run deploy CI_REPOSITORY_URL=; ok "no CI_REPOSITORY_URL -> deploy refused" '[ $RC -ne 0 ] && has "CI_REPOSITORY_URL is not set" && has "fail closed"'; run dry-run CI_REPOSITORY_URL=; ok "no CI_REPOSITORY_URL -> dry-run refused" '[ $RC -ne 0 ]'
run deploy CI_REPOSITORY_URL=/nonexistent/repo.git; ok "unreachable repository -> refused, nothing patched" '[ $RC -ne 0 ] && has "cannot read the tip of master" && [ "$(patches)" = 0 ] && allegacy'
run deploy CI_COMMIT_SHA=73bea44e; ok "a short SHA is rejected" '[ $RC -ne 0 ] && has "not a full 40-hex SHA"'
A=$(git -C $W rev-parse HEAD); ( cd $W; echo y > other; git add -A; git commit -qm other >/dev/null ); run deploy CI_COMMIT_SHA=$A; ok "checkout not at CI_COMMIT_SHA -> refused" '[ $RC -ne 0 ] && has "not at CI_COMMIT_SHA"'
newscenario "an authenticated URL / token never appears in the output"; publish
run deploy CI_REPOSITORY_URL=https://gitlab-ci-token:SECRETTOKEN123@127.0.0.1:1/psia/g15.git; ok "unreachable authenticated URL -> refused" '[ $RC -ne 0 ] && has "cannot read the tip of master"'
ok "NO token and no credentials in the log" '! grep -qE "SECRETTOKEN123|gitlab-ci-token" /tmp/out.txt'
BR=development run smoke CI_REPOSITORY_URL=https://gitlab-ci-token:SECRETTOKEN123@127.0.0.1:1/x.git; ok "smoke fails closed on a bad URL and leaks nothing" '[ $RC -ne 0 ] && has "remote lookup of the master tip via CI_REPOSITORY_URL FAILED" && ! grep -q SECRETTOKEN123 /tmp/out.txt'
newscenario "smoke exercises the exact remote lookup (read-only)"; publish; BR=development run smoke; ok "smoke ok, remote lookup reported, remotes listed by name only" '[ $RC -eq 0 ] && has "git ok: the checkout is readable" && has "remote lookup ok: current tip of master is" && has "SMOKE OK"'; ok "nothing patched" '[ "$(patches)" = 0 ]'
echo; echo "=================== $PASS passed, $FAILN failed ==================="; [ $FAILN -eq 0 ]
