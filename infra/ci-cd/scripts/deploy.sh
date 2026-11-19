#!/bin/sh
# Production deployment for g15 (runs in the ci-tools image on the deploy runner, as ServiceAccount g15-cd/ci-deployer).
#   deploy.sh deploy    roll the selected components to the images published by THIS pipeline, verify, roll back on any failure
#   deploy.sh rollback  restore the state recorded before the last deploy (manual job)
#   deploy.sh dry-run   same checks and server-side dry-run patches, changes nothing
#   deploy.sh smoke     identity / RBAC / admission / state / health checks only, needs no published images (safe on any protected ref)
# Safety model: one lock (cd-state ConfigMap, optimistic concurrency), stale-pipeline guards, only digest-pinned images of the right
# component (also enforced by the cluster's admission policy), never touches Qwen, databases, Secrets or the CronJob's schedule.
set -eu
MODE=${1:-}; case "$MODE" in deploy|rollback|dry-run|smoke) ;; *) echo "usage: $0 deploy|rollback|dry-run|smoke" >&2; exit 2;; esac
# The checkout is created by the runner's helper container (another uid). Git refuses to read a repository owned by someone else
# ("dubious ownership") and then even reports a valid remote as "not a git repository". Trust exactly this workspace via the environment
# (nothing is written to disk).
export GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=safe.directory GIT_CONFIG_VALUE_0="${CI_PROJECT_DIR:-$PWD}"
KUBECTL=${KUBECTL:-kubectl}; NS=${CD_NAMESPACE:-g15-app}; STATE=${CD_STATE_CM:-cd-state}
ORDER="movie-service user-service recommendation-service proxy frontend"            # dependency order
SEQ="movie-service user-service recommendation-service recommendation-agent proxy frontend"      # the agent CronJob follows the service it shares an image with
RSEQ="frontend proxy recommendation-agent recommendation-service user-service movie-service"     # rollback = exact reverse
ROLLOUT_TIMEOUT=${ROLLOUT_TIMEOUT:-300s}; HEALTH=${CD_HEALTH:-1}; CRON=${CD_CRON:-1}; PIPELINE=${CI_PIPELINE_ID:-manual}
SVC=${CD_SVC_DOMAIN:-.g15-app.svc.cluster.local}   # the job pod runs in g15-cd, so service names need their namespace
START=$(date +%s); MAXSEC=${CD_MAX_SECONDS:-1500}          # own deadline (25 min) < job timeout (40 min): a slow deploy rolls back while time remains
WHO="pipeline $PIPELINE by ${GITLAB_USER_LOGIN:-unknown} on ${CI_COMMIT_BRANCH:-n/a}"
PROXY=${CD_HEALTH_PROXY:-http://proxy$SVC}; WORK=$(mktemp -d); LOCKED=0; DONE=0; TOUCHED=""; CHANGED=""
log() { printf '%s %s\n' "$(date -u +%H:%M:%S)" "$*"; }
die() { log "ERROR: $*"; exit 1; }
jqf() { jq "$@"; }

# ---- the CURRENT tip of master, read from GitLab with the job's own credentials (CI_REPOSITORY_URL) --------------------------------------
remote_tip() { # prints the full 40-hex SHA or fails; the authenticated URL is never printed (git's error output is scrubbed)
  [ -n "${CI_REPOSITORY_URL:-}" ] || { log "CI_REPOSITORY_URL is not set" >&2; return 1; }
  _ri=0
  while [ $_ri -lt 3 ]; do
    if _ro=$(git ls-remote -- "$CI_REPOSITORY_URL" refs/heads/master 2>"$WORK/lsremote.err"); then
      _rt=$(printf '%s\n' "$_ro" | awk '$2=="refs/heads/master"{print $1}')
      if [ "$(printf '%s\n' "$_ro" | grep -c .)" = 1 ] && [ ${#_rt} -eq 40 ] && [ -z "$(printf '%s' "$_rt" | tr -d '0-9a-f')" ]; then printf '%s' "$_rt"; return 0; fi
      log "the remote did not return exactly one 40-hex tip for refs/heads/master" >&2; return 1
    fi
    _ri=$((_ri+1)); sleep 3
  done
  log "cannot read the tip of master from GitLab (3 attempts); git said:" >&2
  sed -E 's#[A-Za-z][A-Za-z0-9+.-]*://[^@/[:space:]]*@#<url>#g' "$WORK/lsremote.err" | head -3 >&2
  return 1; }

# ---- component metadata -------------------------------------------------------------------------------------------------------
src_paths() { case $1 in frontend) echo app/frontend;; proxy) echo app/proxy;; user-service|movie-service|recommendation-service) echo "app/backend/$1 app/backend/common";; esac; }
health_url() { case $1 in frontend) echo "http://frontend$SVC:80/";; proxy) echo "http://proxy$SVC:80/";; user-service) echo "http://user-service$SVC:4208/health";; movie-service) echo "http://movie-service$SVC:4206/health";; recommendation-service) echo "http://recommendation-service$SVC:4207/health";; esac; }
valid_component() { case " $ORDER " in *" $1 "*) return 0;; esac; return 1; }

# ---- health ---------------------------------------------------------------------------------------------------------------------
health_ok() { [ "$HEALTH" = 1 ] || return 0; i=0; while [ $i -lt 12 ]; do curl -fsS -o /dev/null --max-time 10 "$1" 2>/dev/null && return 0; i=$((i+1)); sleep 5; done; log "health check failed: $1"; return 1; }
health_all() { health_ok "$PROXY/api/user/health" && health_ok "$PROXY/api/movie/health" && health_ok "$PROXY/api/recommendation/health" && health_ok "$PROXY/"; }

# ---- state (cd-state ConfigMap) ---------------------------------------------------------------------------------------------------
state_get() { $KUBECTL -n "$NS" get cm "$STATE" -o json; }
state_field() { jq -r --arg k "$2" '.data[$k] // ""' "$1"; }
state_patch() { $KUBECTL -n "$NS" patch cm "$STATE" --type=merge -p "$1" >/dev/null; }
finish_state() { # status result [extra data json object]
  body=$(jq -nc --arg s "$1" --arg r "$2" --argjson x "${3:-{\}}" '{data:({status:$s,lockedBy:"",lastResult:$r}+$x)}'); state_patch "$body"; }

# ---- live helpers -----------------------------------------------------------------------------------------------------------------
live_image() { if [ "$1" = recommendation-agent ]; then $KUBECTL -n "$NS" get cronjob recommendation-agent -o jsonpath='{.spec.jobTemplate.spec.template.spec.containers[0].image}'
               else $KUBECTL -n "$NS" get deployment "$1" -o jsonpath='{.spec.template.spec.containers[0].image}'; fi; }
patch_workload() { # name image pullPolicy secret(1|0) [kubectl flag]      (POSIX sh has no local scope: private names only, never touch the caller's c/n/d)
  _pc=$1; [ "$1" = recommendation-agent ] && _pc=agent-scan
  if [ "$4" = 1 ]; then _ps='[{"name":"gitlab-registry"}]'; else _ps=null; fi
  _pp=$(jq -nc --arg n "$_pc" --arg i "$2" --arg p "$3" --argjson s "$_ps" '{containers:[{name:$n,image:$i,imagePullPolicy:$p}],imagePullSecrets:$s}')
  if [ "$1" = recommendation-agent ]; then
    $KUBECTL -n "$NS" patch cronjob recommendation-agent --type=strategic -p "$(jq -nc --argjson p "$_pp" '{spec:{jobTemplate:{spec:{template:{spec:$p}}}}}')" ${5:-} >/dev/null
  else
    $KUBECTL -n "$NS" patch deployment "$1" --type=strategic -p "$(jq -nc --argjson p "$_pp" '{spec:{template:{spec:$p}}}')" ${5:-} >/dev/null
  fi; }
verify_workload() { # name wantImageID : rollout finished, every pod Ready, running exactly the wanted image, no restarts
  [ "$1" = recommendation-agent ] && return 0                                       # a CronJob has no standing pods; checked via spec
  $KUBECTL -n "$NS" rollout status "deployment/$1" --timeout="$ROLLOUT_TIMEOUT" || return 1
  _vd=$($KUBECTL -n "$NS" get deployment "$1" -o json); _vs=$(echo "$_vd" | jq -r '.spec.selector.matchLabels|to_entries|map("\(.key)=\(.value)")|join(",")'); _vr=$(echo "$_vd" | jq -r .spec.replicas)
  $KUBECTL -n "$NS" get pods -l "$_vs" -o json | jq -e --arg want "$2" --argjson reps "$_vr" \
    '[.items[]|select(.metadata.deletionTimestamp==null)] | (length==$reps) and all(.[]; .status.containerStatuses[0].ready==true and .status.containerStatuses[0].imageID==$want and .status.containerStatuses[0].restartCount==0)' >/dev/null; }
cron_invariants() { # prints the invariants, compared with the recorded ones
  $KUBECTL -n "$NS" get cronjob recommendation-agent -o json | jq -c '{suspend:.spec.suspend,schedule:.spec.schedule,concurrencyPolicy:.spec.concurrencyPolicy,AGENT_MAX_QUEUED:(.spec.jobTemplate.spec.template.spec.containers[0].env[]|select(.name=="AGENT_MAX_QUEUED")|.value)}'; }
drift_check() { # live images must equal what cd-state recorded: any difference means someone changed production outside CD
  _dr=0
  for _dc in $ORDER recommendation-agent; do [ "$_dc" = recommendation-agent ] && [ "$CRON" != 1 ] && continue
    _exp=$(jq -r --arg c "$_dc" '.[$c].image // ""' "$WORK/deployed.json"); _liv=$(live_image "$_dc")
    if [ "$_exp" != "$_liv" ]; then log "DRIFT: $_dc runs '$_liv' but cd-state recorded '$_exp'"; _dr=1; fi
  done; return $_dr; }
inference_id() { $KUBECTL -n "$NS" get deployment inference -o jsonpath='{.metadata.generation}/{.metadata.resourceVersion}' 2>/dev/null || echo unavailable; }

# ---- rollback ---------------------------------------------------------------------------------------------------------------------
rollback_touched() { # restore the pre-deploy state recorded in previous.json for every touched workload
  ok=1; log "ROLLBACK of:$TOUCHED"
  for c in $RSEQ; do case " $TOUCHED " in *" $c "*) ;; *) continue;; esac
    e=$(jq -c --arg c "$c" '.[$c]' "$WORK/previous.json"); img=$(echo "$e" | jq -r .image)
    if [ "$(live_image "$c")" = "$img" ]; then log "$c is already on its previous image: nothing to restore"; continue; fi
     pol=$(echo "$e" | jq -r .pullPolicy); sec=0; [ "$(echo "$e" | jq -r .pullSecret)" = true ] && sec=1
    patch_workload "$c" "$img" "$pol" "$sec" || { log "rollback patch failed for $c"; ok=0; continue; }
    want=$img; [ "$(echo "$e" | jq -r .kind)" = legacy ] && want=$(echo "$e" | jq -r .configDigest)       # legacy local images report their config digest
    verify_workload "$c" "$want" || { log "rollback verification failed for $c"; ok=0; }
    case $c in recommendation-agent) ;; *) health_ok "$(health_url "$c")" || ok=0;; esac
  done
  health_all || ok=0
  if [ "$ok" = 1 ]; then finish_state idle "rolled back ($WHO)"; log "ROLLBACK VERIFIED: production is back on the previous images"; return 0; fi
  finish_state rollback_failed "rollback ($WHO) FAILED - manual intervention required"; log "ROLLBACK FAILED: cd-state=rollback_failed, no further deployment will start"; return 1; }
on_exit() { rc=$?; trap - EXIT; set +e
  if [ "$rc" -ne 0 ] && [ "$LOCKED" = 1 ] && [ "$DONE" != 1 ]; then log "FAILURE (exit $rc) while holding the lock"; rollback_touched; fi
  rm -rf -- "${WORK:?}"; exit $rc; }
trap on_exit EXIT
trap 'exit 143' TERM INT HUP                  # a cancelled/timed-out job still reaches the rollback in on_exit

# ---- guards -----------------------------------------------------------------------------------------------------------------------
log "mode=$MODE namespace=$NS pipeline=$PIPELINE commit=${CI_COMMIT_SHA:-none}"
case $MODE in deploy|rollback)
  [ "${CI_PIPELINE_SOURCE:-}" = push ] && [ "${CI_COMMIT_BRANCH:-}" = master ] && [ "${CI_COMMIT_REF_PROTECTED:-}" = true ] || die "deployment is only allowed from a push to the protected branch master";; esac
$KUBECTL -n "$NS" get cm "$STATE" >/dev/null 2>&1 || die "$STATE ConfigMap not found"
state_get > "$WORK/state.json"
jq -r '.data["deployed.json"]' "$WORK/state.json" > "$WORK/deployed.json"; jq -r '.data["previous.json"]' "$WORK/state.json" > "$WORK/previous.json"
jq -r '.data["cronjob.json"]' "$WORK/state.json" > "$WORK/cronjob.json"
status=$(state_field "$WORK/state.json" status); log "cd-state status=$status lastVerifiedCommit=$(state_field "$WORK/state.json" lastVerifiedCommit | cut -c1-12)"

# ---- smoke: identity, permissions, admission, state, health (no published images needed) ------------------------------------------
if [ "$MODE" = smoke ]; then
  log "identity: $($KUBECTL auth whoami -o jsonpath='{.status.userInfo.username}' 2>/dev/null || echo unknown)"
  for c in $ORDER; do [ "$($KUBECTL auth can-i patch "deployment/$c" -n "$NS")" = yes ] || die "cannot patch deployment/$c"; done
  [ "$($KUBECTL auth can-i patch deployment/inference -n "$NS")" = no ] || die "deployer CAN patch the inference Deployment"
  [ "$($KUBECTL auth can-i get secrets -n "$NS")" = no ] || die "deployer CAN read Secrets"
  [ "$($KUBECTL auth can-i create jobs -n "$NS")" = no ] || die "deployer CAN create Jobs"
  log "RBAC ok (named Deployments writable; inference, Secrets, Jobs not)"
  fake=0000000000000000000000000000000000000000000000000000000000000000; REG=${CI_REGISTRY_IMAGE:-registry.rnl.tecnico.ulisboa.pt/psia/groups26/g15}
  if patch_workload frontend "$REG/frontend@sha256:$fake" IfNotPresent 1 --dry-run=server; then log "admission ok: a digest-pinned image of the right component is accepted (dry-run)"; else die "admission REJECTED a valid digest-pinned image"; fi
  if patch_workload frontend "$REG/proxy@sha256:$fake" IfNotPresent 1 --dry-run=server 2>/dev/null; then die "admission FAILED to reject another component's image"; else log "admission ok: another component's image is rejected"; fi
  [ "$(cron_invariants)" = "$(jq -c . "$WORK/cronjob.json")" ] || die "CronJob differs from the recorded invariants: $(cron_invariants)"
  log "CronJob invariants ok: $(cron_invariants)"; log "inference identity (must stay constant): $(inference_id)"
  if [ -n "${CI_COMMIT_SHA:-}" ]; then
    log "git: running as uid $(id -u); checkout owner uid $(stat -c %u "${CI_PROJECT_DIR:-.}" 2>/dev/null || echo ?); remotes configured: $(git remote 2>/dev/null | tr '\n' ' ')"
    [ "$(git rev-parse HEAD 2>/dev/null)" = "$CI_COMMIT_SHA" ] || die "cannot read the checkout or it is not at CI_COMMIT_SHA (git ownership problem?)"
    log "git ok: the checkout is readable and at $(printf '%s' "$CI_COMMIT_SHA" | cut -c1-12)"
    _tip=$(remote_tip) || die "remote lookup of the master tip via CI_REPOSITORY_URL FAILED"
    log "remote lookup ok: current tip of master is $(printf '%s' "$_tip" | cut -c1-12)... ($(if [ "$_tip" = "$CI_COMMIT_SHA" ]; then echo 'this commit'; else echo 'a different commit'; fi))"
  fi
  drift_check && log "no drift: live images equal the cd-state record" || die "production drifted from the cd-state record (changed outside CD?)"
  health_all || die "production health check failed"; log "production health ok"; DONE=1; log "SMOKE OK"; exit 0
fi

# ---- published images of THIS pipeline (deploy | dry-run) ------------------------------------------------------------------------
if [ "$MODE" != rollback ]; then
  : "${CI_COMMIT_SHA:?}" "${CI_REGISTRY_IMAGE:?}"
  case "$CI_COMMIT_SHA" in *[!0-9a-f]*|"") die "CI_COMMIT_SHA is not a full 40-hex SHA";; esac; [ ${#CI_COMMIT_SHA} -eq 40 ] || die "CI_COMMIT_SHA is not a full 40-hex SHA"
  for c in $ORDER; do f="published/$c.json"; [ -s "$f" ] || die "missing $f (the publish job of $c did not succeed)"
    jq -e --arg c "$c" --arg sha "$CI_COMMIT_SHA" --arg repo "$CI_REGISTRY_IMAGE/$c" '.component==$c and .commit==$sha and .repository==$repo and (.digest|test("^sha256:[0-9a-f]{64}$"))' "$f" >/dev/null || die "$f does not describe $c at $CI_COMMIT_SHA"
    echo "$(jq -r .repository "$f")@$(jq -r .digest "$f")" > "$WORK/target.$c"; log "published $c -> $(cat "$WORK/target.$c" | sed 's#.*/##')"; done
  cp "$WORK/target.recommendation-service" "$WORK/target.recommendation-agent"
  if [ -s published/ci-tools.json ]; then jq -e --arg sha "$CI_COMMIT_SHA" '.commit==$sha' published/ci-tools.json >/dev/null || die "ci-tools was not published for this commit"; fi
  # stale-pipeline guards
  if [ "$MODE" = deploy ] || { [ "${CI_COMMIT_BRANCH:-}" = master ] && [ "$MODE" = dry-run ]; }; then
    [ "$(git rev-parse HEAD 2>/dev/null)" = "$CI_COMMIT_SHA" ] || die "cannot read the checkout, or it is not at CI_COMMIT_SHA (git ownership problem?): refusing"
    tip=$(remote_tip) || die "cannot verify that this pipeline is the tip of master: refusing (fail closed)"
    if [ "$tip" != "$CI_COMMIT_SHA" ]; then log "SUPERSEDED: master moved to $tip; this older pipeline will not deploy"; exit 75; fi
    last=$(state_field "$WORK/state.json" lastVerifiedCommit)
    if [ -n "$last" ]; then git cat-file -e "$last^{commit}" 2>/dev/null || die "history does not contain the last verified commit $last"
      git merge-base --is-ancestor "$last" "$CI_COMMIT_SHA" || die "this commit is older than the last verified deployment $last"; fi
  fi
fi

# ---- select components --------------------------------------------------------------------------------------------------------------
if [ "$MODE" = rollback ]; then
  for c in $ORDER recommendation-agent; do prev=$(jq -r --arg c "$c" '.[$c].image' "$WORK/previous.json"); [ "$(live_image "$c")" = "$prev" ] || TOUCHED="$TOUCHED $c"; done
  [ -n "$TOUCHED" ] || { log "nothing to roll back: live images already equal the recorded previous state"; DONE=1; exit 0; }
else
  req=$(echo "${DEPLOY_COMPONENTS:-${CD_COMPONENTS:-frontend}}" | tr ',' ' '); [ "$req" = all ] && req=$ORDER
  for c in $req; do valid_component "$c" || die "unknown component '$c' (valid: $ORDER)"; done
  for c in $ORDER; do case " $req " in *" $c "*) ;; *) continue;; esac
    live=$(live_image "$c"); target=$(cat "$WORK/target.$c")
    if [ "$live" = "$target" ]; then log "$c: already running the target image, skip"; continue; fi
    kind=$(jq -r --arg c "$c" '.[$c].kind // "legacy"' "$WORK/deployed.json"); last=$(jq -r --arg c "$c" '.[$c].commit // ""' "$WORK/deployed.json")
    if [ "${DEPLOY_FORCE:-0}" = 1 ] || [ "$kind" = legacy ] || [ -z "$last" ]; then CHANGED="$CHANGED $c"; log "$c: will deploy ($kind -> registry digest)"
    elif ! git cat-file -e "$last^{commit}" 2>/dev/null || ! git diff --quiet "$last" "$CI_COMMIT_SHA" -- $(src_paths "$c"); then CHANGED="$CHANGED $c"; log "$c: sources changed since $(echo "$last" | cut -c1-12): will deploy"
    else log "$c: sources unchanged since $(echo "$last" | cut -c1-12): skip (no restart)"; fi; done
  TOUCHED=$CHANGED; case " $CHANGED " in *" recommendation-service "*) [ "$CRON" = 1 ] && TOUCHED="$TOUCHED recommendation-agent";; esac
  [ -n "$TOUCHED" ] || { log "nothing to deploy"; DONE=1; exit 0; }
fi
log "workloads in scope:$TOUCHED"

# ---- preflight: production must be healthy and the invariants must hold BEFORE anything changes ---------------------------------------
case "$status" in
  idle) ;;
  in_progress|rollback_failed) if [ "$MODE" = rollback ]; then log "RECOVERY: cd-state is '$status' (lock left by a killed or failed run). The production resource_group guarantees no other deployment job is running, so this rollback job takes over the lock."
                                else die "cd-state status is '$status' (not idle): refusing to deploy. Run the manual deploy:rollback job (it can recover this state) or have a person check the cluster"; fi;;
  *) die "unknown cd-state status '$status'";;
esac
INF0=$(inference_id)
if [ "$MODE" != rollback ]; then      # a rollback exists to repair an unhealthy system, so it must NOT require health up front
  [ "$CRON" != 1 ] || [ "$(cron_invariants)" = "$(jq -c . "$WORK/cronjob.json")" ] || die "CronJob invariants differ from the recorded ones: $(cron_invariants)"
  drift_check || die "production drifted from the cd-state record (someone changed it outside CD): refusing to deploy over unexplained state"
  health_all || die "production is not healthy before the deployment: nothing was changed"
fi

if [ "$MODE" = dry-run ]; then
  for c in $TOUCHED; do if patch_workload "$c" "$(cat "$WORK/target.$c")" IfNotPresent 1 --dry-run=server; then log "dry-run patch accepted for $c"; else die "dry-run patch REJECTED for $c"; fi; done
  log "DRY-RUN OK (nothing changed)"; DONE=1; exit 0
fi

# ---- take the lock (compare-and-swap on the ConfigMap's resourceVersion) ------------------------------------------------------------
rv=$(jq -r .metadata.resourceVersion "$WORK/state.json")
if [ "$MODE" = deploy ]; then      # remember the state we can return to; a rollback job must keep the one already recorded
  body=$(jq -nc --arg rv "$rv" --arg who "$PIPELINE" --arg prev "$(cat "$WORK/deployed.json")" '{metadata:{resourceVersion:$rv},data:{status:"in_progress",lockedBy:$who,"previous.json":$prev}}')
  cp "$WORK/deployed.json" "$WORK/previous.json"
else
  body=$(jq -nc --arg rv "$rv" --arg who "$PIPELINE" '{metadata:{resourceVersion:$rv},data:{status:"in_progress",lockedBy:$who}}')
fi
$KUBECTL -n "$NS" patch cm "$STATE" --type=merge -p "$body" >/dev/null || die "could not take the lock (cd-state changed under us)"
LOCKED=1; log "lock taken (cd-state=in_progress)"

# ---- roll ------------------------------------------------------------------------------------------------------------------------------
if [ "$MODE" = rollback ]; then
  DONE=1; LOCKED=0                                                                    # rollback_touched sets the final state itself
  if rollback_touched; then finish_state idle "rollback job done ($WHO)" "$(jq -nc --arg d "$(cat "$WORK/previous.json")" '{"deployed.json":$d}')"; exit 0; fi
  exit 1
fi
for c in $SEQ; do case " $TOUCHED " in *" $c "*) ;; *) continue;; esac
  [ $(( $(date +%s) - START )) -lt "$MAXSEC" ] || die "deadline of ${MAXSEC}s reached before $c: stopping and rolling back while there is time"
  target=$(cat "$WORK/target.$c"); log "deploying $c -> ${target##*/}"
  patch_workload "$c" "$target" IfNotPresent 1
  verify_workload "$c" "$target" || die "$c did not become healthy on the new image"
  [ "$(live_image "$c")" = "$target" ] || die "$c is not on the expected image after patching"
  case $c in recommendation-agent) [ "$(cron_invariants)" = "$(jq -c . "$WORK/cronjob.json")" ] || die "CronJob invariants changed: $(cron_invariants)";; *) health_ok "$(health_url "$c")" || die "$c health check failed";; esac
  health_all || die "end-to-end health failed after $c"
  log "$c OK"; done
# ---- final verification ------------------------------------------------------------------------------------------------------------
[ "$INF0" = "$(inference_id)" ] || die "the inference Deployment changed during the deployment ($INF0 -> $(inference_id))"
[ "$CRON" != 1 ] || [ "$(cron_invariants)" = "$(jq -c . "$WORK/cronjob.json")" ] || die "CronJob invariants changed"
for c in $ORDER; do d=$($KUBECTL -n "$NS" get deployment "$c" -o json | jq -r '(.status.readyReplicas//0)==.spec.replicas'); [ "$d" = true ] || die "$c is not fully ready"; done
health_all || die "final end-to-end health failed"
now=$(date -u +%Y-%m-%dT%H:%M:%SZ); new=$(cat "$WORK/deployed.json")
for c in $TOUCHED; do new=$(echo "$new" | jq -c --arg c "$c" --arg i "$(cat "$WORK/target.$c")" --arg sha "$CI_COMMIT_SHA" --arg at "$now" '.[$c]={image:$i,pullPolicy:"IfNotPresent",pullSecret:true,kind:"registry",configDigest:"",commit:$sha,at:$at}'); done
DONE=1; finish_state idle "deployed$TOUCHED at $CI_COMMIT_SHA ($WHO)" "$(jq -nc --arg d "$new" --arg sha "$CI_COMMIT_SHA" '{"deployed.json":$d,lastVerifiedCommit:$sha}')"
log "DEPLOYMENT VERIFIED:$TOUCHED (inference untouched: $(inference_id), CronJob invariants unchanged)"
