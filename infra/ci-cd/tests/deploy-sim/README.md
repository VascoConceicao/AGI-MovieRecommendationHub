# deploy.sh simulation (no cluster needed)
`kubectl` is a small simulator (Deployments, CronJob, Pods, the cd-state ConfigMap with optimistic locking, fault injection); `driver.sh`
runs 23 scenarios (success, change detection, rollout/health/admission failures, lock races, stale pipelines, drift, cancel, hard kill,
recovery) with real git repos. Run from the repository root:
`docker run --rm -v "$PWD/infra/ci-cd/tests/deploy-sim:/sim:ro" -v "$PWD/infra/ci-cd/scripts/deploy.sh:/deploy.sh:ro" -v "$PWD/infra/ci-cd/tests/deploy-sim/cd-state.fixture.json:/m5/cd-state.json:ro" alpine sh -c 'apk add --no-cache bash jq git python3 >/dev/null; bash /sim/driver.sh'`
