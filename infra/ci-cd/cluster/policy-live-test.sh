#!/bin/bash
# Runs ON cp1 AFTER the policies are applied. EVERY mutating call is --dry-run=server (nothing is changed). Impersonates the deployer.
# ok   = must be admitted.  pol = must be rejected BY THE ADMISSION POLICY.  rbac = must be rejected by RBAC ("forbidden").
KC="sudo kubectl --kubeconfig=/etc/kubernetes/admin.conf"; AS="--as=system:serviceaccount:g15-cd:ci-deployer"; bad=0; n=0
D=0000000000000000000000000000000000000000000000000000000000000000
R=registry.rnl.tecnico.ulisboa.pt/psia/groups26/g15
chk() { # mode desc cmd...
  mode=$1; desc=$2; shift 2; n=$((n+1)); out=$("$@" 2>&1); rc=$?; s=MISMATCH
  case $mode in
    ok)   [ $rc -eq 0 ] && s=ok ;;
    pol)  [ $rc -ne 0 ] && echo "$out" | grep -q "ValidatingAdmissionPolicy" && s=ok ;;
    rbac) [ $rc -ne 0 ] && echo "$out" | grep -qi "forbidden" && s=ok ;;
  esac
  [ $s = ok ] || bad=$((bad+1)); printf '%-9s %-4s %s\n' "$s" "$mode" "$desc"
  [ $s = ok ] || echo "      rc=$rc -> $(echo "$out" | head -2 | cut -c1-260)"
}
dp() { c=$1; shift; $KC -n g15-app patch deployment "$c" --type=strategic -p "$1" $AS --dry-run=server; }    # strategic patch of a Deployment
cj() { $KC -n g15-app patch cronjob recommendation-agent --type="$1" -p "$2" $AS --dry-run=server; }
ctr() { echo "{\"spec\":{\"template\":{\"spec\":{\"containers\":[{\"name\":\"$1\",$2}]}}}}"; }                  # container-level patch body
pod() { echo "{\"spec\":{\"template\":{\"spec\":{$1}}}}"; }                                                     # pod-level patch body
cpath=/spec/jobTemplate/spec/template/spec
echo "##### ALLOWED (approved image-related changes)"
for c in frontend proxy user-service movie-service recommendation-service; do
  chk ok "$c: own registry digest" dp $c "$(ctr $c "\"image\":\"$R/$c@sha256:$D\"")"; done
chk ok "frontend: digest + IfNotPresent + approved pull secret" dp frontend "{\"spec\":{\"template\":{\"spec\":{\"containers\":[{\"name\":\"frontend\",\"image\":\"$R/frontend@sha256:$D\",\"imagePullPolicy\":\"IfNotPresent\"}],\"imagePullSecrets\":[{\"name\":\"gitlab-registry\"}]}}}}"
chk ok "frontend: legacy local image + Never (rollback form)" dp frontend "$(ctr frontend '"image":"g15-frontend:local","imagePullPolicy":"Never"')"
chk ok "agent CronJob: recommendation-service digest" cj json "[{\"op\":\"replace\",\"path\":\"$cpath/containers/0/image\",\"value\":\"$R/recommendation-service@sha256:$D\"}]"
chk ok "agent CronJob: digest + IfNotPresent + pull secret" cj json "[{\"op\":\"replace\",\"path\":\"$cpath/containers/0/image\",\"value\":\"$R/recommendation-service@sha256:$D\"},{\"op\":\"replace\",\"path\":\"$cpath/containers/0/imagePullPolicy\",\"value\":\"IfNotPresent\"},{\"op\":\"add\",\"path\":\"$cpath/imagePullSecrets\",\"value\":[{\"name\":\"gitlab-registry\"}]}]"
echo "##### DENIED BY THE ADMISSION POLICY: images"
chk pol "frontend: another component's image"           dp frontend "$(ctr frontend "\"image\":\"$R/proxy@sha256:$D\"")"
chk pol "frontend: mutable tag"                         dp frontend "$(ctr frontend "\"image\":\"$R/frontend:latest\"")"
chk pol "frontend: unapproved registry"                 dp frontend "$(ctr frontend "\"image\":\"docker.io/evil/frontend@sha256:$D\"")"
chk pol "frontend: uppercase/invalid digest"            dp frontend "$(ctr frontend "\"image\":\"$R/frontend@sha256:ABCDEF\"")"
chk pol "frontend: another component's legacy image"    dp frontend "$(ctr frontend '"image":"g15-proxy:local"')"
chk pol "frontend: pullPolicy Always"                   dp frontend "$(ctr frontend '"imagePullPolicy":"Always"')"
chk pol "frontend: other pull secret"                   dp frontend "$(pod '"imagePullSecrets":[{"name":"g15-db-passwords"}]')"
chk pol "agent CronJob: another component's image"      cj json "[{\"op\":\"replace\",\"path\":\"$cpath/containers/0/image\",\"value\":\"$R/frontend@sha256:$D\"}]"
chk pol "agent CronJob: mutable tag"                    cj json "[{\"op\":\"replace\",\"path\":\"$cpath/containers/0/image\",\"value\":\"$R/recommendation-service:latest\"}]"
echo "##### DENIED BY THE ADMISSION POLICY: everything else in a Deployment"
chk pol "replicas -> 0"                                 $KC -n g15-app patch deployment frontend --type=merge -p '{"spec":{"replicas":0}}' $AS --dry-run=server
chk pol "env var added"                                 dp frontend "$(ctr frontend '"env":[{"name":"X","value":"1"}]')"
chk pol "command changed"                               dp frontend "$(ctr frontend '"command":["sh","-c","sleep 1"]')"
chk pol "args changed"                                  dp frontend "$(ctr frontend '"args":["--x"]')"
chk pol "resource limits changed"                       dp frontend "$(ctr frontend '"resources":{"limits":{"cpu":"4","memory":"8Gi"}}')"
chk pol "privileged container"                          dp frontend "$(ctr frontend '"securityContext":{"privileged":true}')"
chk pol "added capability"                              dp frontend "$(ctr frontend '"securityContext":{"capabilities":{"add":["SYS_ADMIN"]}}')"
chk pol "hostNetwork"                                   dp frontend "$(pod '"hostNetwork":true')"
chk pol "hostPID"                                       dp frontend "$(pod '"hostPID":true')"
chk pol "hostPath volume"                               dp frontend "$(pod '"volumes":[{"name":"h","hostPath":{"path":"/"}}]')"
chk pol "serviceAccountName changed"                    dp frontend "$(pod '"serviceAccountName":"default"')"
chk pol "automountServiceAccountToken"                  dp frontend "$(pod '"automountServiceAccountToken":true')"
chk pol "nodeSelector (placement) changed"              dp frontend "$(pod '"nodeSelector":{"kubernetes.io/hostname":"g15-worker1"}')"
chk pol "nodeName pinned"                               dp frontend "$(pod '"nodeName":"g15-worker1"')"
chk pol "tolerations added"                             dp frontend "$(pod '"tolerations":[{"operator":"Exists"}]')"
chk pol "pod securityContext"                           dp frontend "$(pod '"securityContext":{"runAsUser":0}')"
chk pol "init container added"                          dp frontend "$(pod '"initContainers":[{"name":"i","image":"busybox"}]')"
chk pol "extra container added"                         dp frontend "$(pod '"containers":[{"name":"frontend"},{"name":"sidecar","image":"busybox"}]')"
chk pol "readiness probe changed"                       dp frontend "$(ctr frontend '"readinessProbe":{"httpGet":{"path":"/x","port":80}}')"
chk pol "lifecycle hook added"                          dp frontend "$(ctr frontend '"lifecycle":{"preStop":{"exec":{"command":["true"]}}}')"
chk pol "strategy changed"                              $KC -n g15-app patch deployment frontend --type=merge -p '{"spec":{"strategy":{"type":"Recreate","rollingUpdate":null}}}' $AS --dry-run=server
chk pol "object labels changed"                         $KC -n g15-app patch deployment frontend --type=merge -p '{"metadata":{"labels":{"x":"y"}}}' $AS --dry-run=server
chk pol "pod template labels changed"                   $KC -n g15-app patch deployment frontend --type=merge -p '{"spec":{"template":{"metadata":{"labels":{"x":"y"}}}}}' $AS --dry-run=server
echo "##### DENIED BY THE ADMISSION POLICY: the Background Agent CronJob"
chk pol "suspend -> true"                               cj merge '{"spec":{"suspend":true}}'
chk pol "schedule changed"                              cj merge '{"spec":{"schedule":"* * * * *"}}'
chk pol "concurrencyPolicy -> Allow"                    cj merge '{"spec":{"concurrencyPolicy":"Allow"}}'
chk pol "startingDeadlineSeconds"                       cj merge '{"spec":{"startingDeadlineSeconds":5}}'
chk pol "history limits"                                cj merge '{"spec":{"successfulJobsHistoryLimit":50}}'
chk pol "jobTemplate backoffLimit"                      cj merge '{"spec":{"jobTemplate":{"spec":{"backoffLimit":9}}}}'
chk pol "jobTemplate activeDeadlineSeconds"             cj merge '{"spec":{"jobTemplate":{"spec":{"activeDeadlineSeconds":99999}}}}'
chk pol "jobTemplate ttlSecondsAfterFinished"           cj merge '{"spec":{"jobTemplate":{"spec":{"ttlSecondsAfterFinished":1}}}}'
chk pol "AGENT_MAX_QUEUED env raised"                   cj json "[{\"op\":\"add\",\"path\":\"$cpath/containers/0/env/-\",\"value\":{\"name\":\"AGENT_MAX_QUEUED\",\"value\":\"500\"}}]"
chk pol "container command changed"                     cj json "[{\"op\":\"add\",\"path\":\"$cpath/containers/0/command\",\"value\":[\"sh\"]}]"
chk pol "resource limits changed"                       cj json "[{\"op\":\"replace\",\"path\":\"$cpath/containers/0/resources/limits/memory\",\"value\":\"64Gi\"}]"
chk pol "hostNetwork"                                   cj json "[{\"op\":\"add\",\"path\":\"$cpath/hostNetwork\",\"value\":true}]"
chk pol "serviceAccountName"                            cj json "[{\"op\":\"add\",\"path\":\"$cpath/serviceAccountName\",\"value\":\"default\"}]"
echo "##### DENIED BY RBAC (never reaches admission)"
chk rbac "inference Deployment (Qwen)"                  $KC -n g15-app patch deployment inference --type=merge -p '{"spec":{"replicas":1}}' $AS --dry-run=server
chk rbac "delete a Deployment"                          $KC -n g15-app delete deployment frontend $AS --dry-run=server
chk rbac "create a Job (extra scan)"                    $KC -n g15-app create job x --image=busybox $AS --dry-run=server
chk rbac "create a CronJob"                             $KC -n g15-app create cronjob x --image=busybox --schedule='* * * * *' $AS --dry-run=server
chk rbac "read a Secret"                                $KC -n g15-app get secret g15-db-passwords $AS
chk rbac "read agent-context Secret"                    $KC -n g15-app get secret g15-agent-context $AS
chk rbac "patch a StatefulSet (PostgreSQL)"             $KC -n g15-app patch statefulset user-db --type=merge -p '{"spec":{"replicas":0}}' $AS --dry-run=server
chk rbac "read PVCs"                                    $KC -n g15-app get pvc $AS
chk rbac "patch another ConfigMap"                      $KC -n g15-app patch configmap g15-app-config --type=merge -p '{"data":{"x":"y"}}' $AS --dry-run=server
chk rbac "other namespace (g15-ci)"                     $KC -n g15-ci patch deployment gitlab-runner --type=merge -p '{"spec":{"replicas":0}}' $AS --dry-run=server
chk rbac "scale subresource"                            $KC -n g15-app scale deployment frontend --replicas=0 $AS --dry-run=server
echo "##### ISOLATION: the policy must NOT affect anyone else (admin / controllers); dry-run only"
chk ok "admin: add env to frontend (policy not applicable)"      $KC -n g15-app patch deployment frontend --type=strategic -p "$(ctr frontend '"env":[{"name":"X","value":"1"}]')" --dry-run=server
chk ok "admin: suspend the CronJob (policy not applicable)"      $KC -n g15-app patch cronjob recommendation-agent --type=merge -p '{"spec":{"suspend":true}}' --dry-run=server
chk ok "admin: scale frontend (policy not applicable)"           $KC -n g15-app patch deployment frontend --type=merge -p '{"spec":{"replicas":2}}' --dry-run=server
chk ok "admin: change inference (policy not applicable)"         $KC -n g15-app patch deployment inference --type=merge -p '{"spec":{"replicas":1}}' --dry-run=server
echo; echo "total checks: $n | mismatches: $bad"; [ $bad -eq 0 ] && echo "POLICY LIVE TESTS OK" || { echo "POLICY LIVE TESTS HAVE MISMATCHES"; exit 1; }
