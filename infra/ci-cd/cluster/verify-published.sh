#!/bin/bash
# Runs ON cp1:   EXPECTED_SHA=<full 40-hex master commit> bash verify-published.sh
# STRICT, read-only registry verification through a short-lived pod that mounts the READ-ONLY pull secret as a volume (never read or printed).
# Fails unless, for ALL SIX components, the exact tag sha-<EXPECTED_SHA> exists, its manifest is a single linux/amd64 image whose
# org.opencontainers.image.revision label equals EXPECTED_SHA, and the six manifest digests are pairwise distinct.
set -u
SHA=${EXPECTED_SHA:-}; [[ "$SHA" =~ ^[0-9a-f]{40}$ ]] || { echo "EXPECTED_SHA must be the full 40-hex commit SHA"; exit 2; }
KC="sudo kubectl --kubeconfig=/etc/kubernetes/admin.conf"; NS=g15-cd; P=m5-verify
SKO=quay.io/skopeo/stable@sha256:2b7d76dde38c5924e1945348840c58786fc192201f2fd545832e58b53d26f7b8
$KC -n $NS get secret gitlab-registry-read >/dev/null 2>&1 || { echo "secret g15-cd/gitlab-registry-read does not exist yet"; exit 1; }
$KC -n $NS delete pod $P --ignore-not-found >/dev/null 2>&1
$KC apply -f - >/dev/null <<YAML
apiVersion: v1
kind: Pod
metadata: {name: $P, namespace: $NS, labels: {app: m5-verify}}
spec:
  restartPolicy: Never
  automountServiceAccountToken: false
  activeDeadlineSeconds: 600
  securityContext: {runAsNonRoot: true, runAsUser: 1000, fsGroup: 1000}
  containers:
    - name: skopeo
      image: $SKO
      command: ["sleep", "500"]
      env: [{name: HOME, value: /tmp}]
      securityContext: {allowPrivilegeEscalation: false, capabilities: {drop: ["ALL"]}}
      resources: {requests: {cpu: 50m, memory: 64Mi}, limits: {cpu: 250m, memory: 256Mi}}
      volumeMounts: [{name: auth, mountPath: /auth, readOnly: true}, {name: tmp, mountPath: /tmp}]
  volumes:
    - {name: auth, secret: {secretName: gitlab-registry-read, defaultMode: 0440}}
    - {name: tmp, emptyDir: {sizeLimit: 128Mi}}
YAML
$KC -n $NS wait --for=condition=Ready pod/$P --timeout=120s >/dev/null || { echo "verify pod did not start"; $KC -n $NS describe pod $P | tail -8; exit 1; }
$KC -n $NS exec $P -- env SHA="$SHA" bash -c '
REPO=registry.rnl.tecnico.ulisboa.pt/psia/groups26/g15; A="--authfile /auth/.dockerconfigjson"; bad=0; seen=""
for c in frontend proxy user-service movie-service recommendation-service ci-tools; do
  raw=$(skopeo inspect --raw $A docker://$REPO/$c:sha-$SHA 2>/tmp/err) || { echo "FAIL $c: tag sha-$SHA not found ($(head -c 110 /tmp/err))"; bad=1; continue; }
  dig=sha256:$(printf "%s" "$raw" | sha256sum | cut -d" " -f1)
  media=$(printf "%s" "$raw" | grep -o "\"mediaType\": *\"[^\"]*\"" | head -1 | grep -o "application[^\"]*")
  cfgd=$(printf "%s" "$raw" | tr -d "\n " | grep -o "\"config\":{[^}]*" | grep -o "sha256:[0-9a-f]\{64\}" | head -1)
  conf=$(skopeo inspect --config $A docker://$REPO/$c@$dig); rev=$(printf "%s" "$conf" | grep -o "\"org.opencontainers.image.revision\": *\"[0-9a-f]*\"" | grep -o "[0-9a-f]\{40\}" | head -1)
  arch=$(printf "%s" "$conf" | grep -o "\"architecture\": *\"[a-z0-9]*\"" | grep -o "[a-z0-9]*\"$" | tr -d "\""); os=$(printf "%s" "$conf" | grep -o "\"os\": *\"[a-z]*\"" | grep -o "[a-z]*\"$" | tr -d "\"")
  st=ok; [ "$rev" = "$SHA" ] || st="REVISION-MISMATCH($rev)"; [ "$os/$arch" = linux/amd64 ] || st="$st WRONG-PLATFORM($os/$arch)"; case "$media" in *index*|*manifest.list*) st="$st IS-AN-INDEX";; esac
  case " $seen " in *" $dig "*) st="$st DUPLICATE-DIGEST";; esac; seen="$seen $dig"
  echo "RESULT $c digest=$dig config=${cfgd:-?} revision=${rev:-none} platform=$os/$arch media=${media##*.} => $st"; [ "$st" = ok ] || bad=1
done
[ $bad -eq 0 ] && echo "ALL SIX IMAGES VERIFIED for commit $SHA" || echo "VERIFICATION FAILED"; exit $bad'
rc=$?; $KC -n $NS delete pod $P --wait=false >/dev/null 2>&1; exit $rc
