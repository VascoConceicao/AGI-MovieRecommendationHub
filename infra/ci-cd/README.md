# GitLab CI

The test runner (`g15-ci`) lives in the existing Kubernetes cluster, namespace `g15-ci`.
It starts up to two temporary test pods at a time. No extra VM. Two further
project runners handle delivery: `g15-build` (namespace `g15-build`, tag
`g15-build`, protected, one job at a time, Kaniko and Skopeo only) and
`g15-deploy` (namespace `g15-cd`, tag `g15-deploy`, protected, one job at a
time, ServiceAccount `ci-deployer`).

Root `.gitlab-ci.yml` defines when pipelines run and includes test jobs from
`pipeline.yml` here. Only pushes to `development` or `master`, including
merges, run five Python suites and the frontend suite. Merge requests and
feature branch pushes do not create pipelines. Reports stay in GitLab for
one week.

There is no `stage` branch. Work goes from feature branches into `development`,
then into `master`. Delivery jobs live in `delivery.yml`. On `development` they
exist only as manual smoke jobs; nothing is built, published or deployed there.
On `master`, after all tests pass, the build runner (tag `g15-build`, protected,
Kaniko + Skopeo, no privileged containers) builds six images (no push) and
publishes each to the project registry with the per-job token under an
immutable `sha-<full commit>` tag; the deploy runner then runs the deployment
jobs below. Deployment runs only after successful tests on a push to `master`
(including merges), never in merge request pipelines or on `development`.

## Branch protection

Both branches require merge requests. Tests run after merge and do not block
merging. Direct pushes and force pushes are disabled. Which roles may merge into each branch is a
GitLab protected-branch setting (Settings > Repository > Protected branches); check it there.

These rules are GitLab project settings, separate from CI YAML. Changing them
needs a Maintainer account. `GITLAB_API_TOKEN` in the local `.env` can hold
a short-lived token with `api` scope for this setup. It is not used by CI jobs.

After the CI configuration is pushed, apply and verify these settings once:

```sh
python3 infra/ci-cd/scripts/configure-project.py
```

The API token can be revoked afterwards. Branch rules persist in GitLab.

## Install

Needs `kubectl`, Helm, Python 3, and the cluster kubeconfig.

1. GitLab → Settings → CI/CD → Runners → New project runner.
   Enable **Run untagged jobs**. Leave **Paused** and **Protected** off.
   Name it `g15-ci`. Reset any token previously shared in screenshots.
2. Put its new `glrt-` authentication token in `infra/ci-cd/.env`:

   ```dotenv
   GITLAB_RUNNER_TOKEN=glrt-your-token
   ```

   This file is ignored by Git. `.env.example` is the shareable template.
3. Run:

   ```sh
   sh infra/ci-cd/scripts/install-runner.sh
   ```

Set `KUBECONFIG` to use another kubeconfig. An optional first argument sets
another `.env` file. Chart version is pinned in the install script.

Setup is once per runner. Normal pushes and pod/VM restarts need no new
registration. If the cluster is rebuilt or the runner is deleted/reset in
GitLab, run setup again with a valid token. The installed runner reads its
token from a Kubernetes Secret; it does not need the local `.env` for jobs.

The runner needs outbound access to GitLab and package/image registries.
No public inbound runner port needed. Test pods use an unprivileged service
account with no API token or application secrets. The runner manager can
manage job pods only in its namespace. Treat project code as trusted: jobs
share the cluster network with the application.

## Check

```sh
kubectl --kubeconfig=infra/terraform/cluster-gcp/kubeconfig.out -n g15-ci get pods
kubectl --kubeconfig=infra/terraform/cluster-gcp/kubeconfig.out -n g15-ci logs deployment/gitlab-runner --tail=30
```

GitLab must show the runner online. Merge the CI files into `development`
to run a pipeline. Merging into `master` also starts its own test pipeline.

## Capacity

The nodes have 8 GB each and also host the app and monitoring. Each test
container requests 512 MiB and is limited to 1 GiB; its helper is limited to
128 MiB. Up to two jobs run at a time. Large tests may still run out of
memory or slow the app. Check resource use before raising concurrency further.

Dependencies install fresh from lockfiles. Shared CI cache is not configured.
Frontend CI uses one Vitest worker thread and one Angular build worker.
Its config stays here; local test defaults are unchanged.
Pausing the runner in GitLab stops new jobs; the app keeps running.
Pause it and wait for active jobs before upgrading the runner.

Official setup: https://docs.gitlab.com/runner/install/kubernetes/

## Production deployment (master only)

`delivery.yml` adds the `deploy` stage, run by the deploy runner (tag `g15-deploy`, ServiceAccount `g15-cd/ci-deployer`).
It only exists for a push to the protected branch `master`, after every test, build and publish job has succeeded.

| Job | When | What it does |
|---|---|---|
| `deploy:dry-run` | automatic on master | all checks and server-side dry-run patches; changes nothing |
| `deploy:production` | **automatic** while the protected CI/CD variable `CD_AUTO_DEPLOY` is `true` (set in this project); manual when it is unset | rolls the selected components to the digests published by this pipeline |
| `deploy:rollback` | manual | restores the state recorded before the last deployment |
| `smoke:deploy-runner` | manual, `development` or `master` | identity, RBAC, admission policy, state and health checks; read-only |

`infra/ci-cd/scripts/deploy.sh` takes a lock in the `cd-state` ConfigMap (compare-and-swap), refuses a pipeline that is not the tip of
`master` or is older than the last verified deployment, deploys in dependency order (movie, user, recommendation + the agent CronJob,
proxy, frontend), checks that every pod runs exactly the published digest, is Ready and has not restarted, health-checks the services,
verifies that the CronJob's schedule/suspend/concurrency/`AGENT_MAX_QUEUED` and the Qwen Deployment did not change, and rolls back
automatically on any failure. Components whose sources did not change since their last deployment are left alone (no restart).
The deploy identity (`g15-cd/ci-deployer`) can only patch the five application Deployments and the agent CronJob and read/patch `cd-state`; two
ValidatingAdmissionPolicies limit those patches to the container image (digest-pinned, of the same component), `imagePullPolicy` and the
`gitlab-registry` pull secret.

Which components: set `DEPLOY_COMPONENTS` when playing `deploy:production` (`all` or a list); otherwise the CI/CD variable
`CD_COMPONENTS` is used (default `frontend`; set to `all` in this project). `cd-state.status` must be `idle`; `in_progress` or `rollback_failed` blocks new deployments until
a person has checked the cluster and reset it (`kubectl -n g15-app patch cm cd-state --type merge -p '{"data":{"status":"idle","lockedBy":""}}'`).
The images may be pulled only through the `gitlab-registry` pull secret (read_registry deploy token), created with `cluster/load-pull-secrets.sh`.

## Initial setup of continuous deployment (once per cluster)

The test runner above is installed with `install-runner.sh`. Continuous delivery needs a one-time setup by a cluster admin and a GitLab Maintainer, after the
cluster and the application exist (initial deployment: root `README.md`). The cluster objects are in [`cluster/`](cluster/README.md) and the GitLab settings in
[`cluster/GITLAB-UI-STEPS.md`](cluster/GITLAB-UI-STEPS.md).

1. **Cluster objects** (admin kubeconfig, in the order given in `cluster/README.md`): namespaces `g15-build` and `g15-cd`, the job ServiceAccounts, the `ci-deployer`
   Role and RoleBinding in `g15-app`, and the admission policies.
2. **GitLab runners**: create two project runners in the GitLab UI, `g15-build` and `g15-deploy`, with *Run untagged jobs* off, *Protected* on and *Lock to current
   projects* on. Load each `glrt-` token with `sh infra/ci-cd/cluster/load-runner-token.sh build|deploy` (hidden prompt) and install the runner with
   `sh infra/ci-cd/cluster/render-runner.sh build|deploy | kubectl apply -f -`.
3. **Registry pull credentials**: create a deploy token with the `read_registry` scope only (set an expiry date; no `write_registry` token is needed, because
   publishing uses the per-job token) and load it with `sh infra/ci-cd/cluster/load-pull-secrets.sh`. It creates `gitlab-registry` in `g15-app` (the kubelet pulls
   application images with it) and `gitlab-registry-read` in `g15-cd` (pulls the deploy image). Rerunning it rotates the credential.
4. **Deploy image digest**: the deploy jobs run in the `ci-tools` image, pinned by digest in `delivery.yml` and in `cluster/values-deploy.yaml`; the two must match.
   A digest can only be taken from a published image, so after the first `master` pipeline has published `ci-tools`, copy its digest (printed by
   `cluster/verify-published.sh`) into both files and render the deploy runner again.
5. **Protected CI/CD variables** (Settings > CI/CD > Variables, flag *Protected*): `CD_COMPONENTS` (`all`; the default is `frontend`) and `CD_AUTO_DEPLOY` (`true` for
   automatic deployment; leave it unset for manual deployment).
6. **The `cd-state` ConfigMap** (next section).
7. **Background agent**: the CronJob ships suspended; activate it as described in `infra/k8s/app/README.md`, then make `cronjob.json` below match it.

`load-runner-token.sh` and `load-pull-secrets.sh` reach the control plane with `gcloud compute ssh g15-cp1 --zone=europe-southwest1-a --project=prefab-conquest-511709-j5`;
in another project or zone, edit that line first.

### The `cd-state` ConfigMap

`deploy.sh` needs the ConfigMap `cd-state` in namespace `g15-app` and stops with "ConfigMap not found" without it. The deploy identity can read and patch it but not
create it, so a cluster admin creates it once. No script generates it. The repository contains an example with the exact shape,
`infra/ci-cd/tests/deploy-sim/cd-state.fixture.json` (a complete ConfigMap manifest used by the deployment simulator); replace its values with those of your cluster.
What `deploy.sh` reads and writes:

| Key | Content |
|---|---|
| `status` | `idle`; the job sets `in_progress` while it holds the lock, and `rollback_failed` if a rollback fails |
| `lockedBy` | empty when idle, otherwise the pipeline holding the lock |
| `lastVerifiedCommit` | empty before the first deployment, afterwards the last commit that was deployed and verified |
| `lastResult` | free text written by the job |
| `deployed.json` | one entry per component (`frontend`, `proxy`, `user-service`, `movie-service`, `recommendation-service`, `recommendation-agent`) with `image`, `pullPolicy`, `pullSecret`, `kind`, `configDigest`, `commit`, `at`; it must equal what runs in the cluster, otherwise the job reports drift |
| `previous.json` | same shape; the state `deploy:rollback` restores. The deploy job overwrites it with `deployed.json` when it takes the lock; initially it equals `deployed.json` |
| `cronjob.json` | the agent CronJob's invariants `suspend`, `schedule`, `concurrencyPolicy` and `AGENT_MAX_QUEUED` (a string), in this key order; the job compares it textually with the live CronJob, so the values must equal the live ones |
| `legacy.json`, `inference.json` | records of the initial images and of the Qwen Deployment's generation and resourceVersion; kept for reference, not read by `deploy.sh` |

For Deployments that still run the locally built images, each `deployed.json` entry is `kind: legacy`, `image: g15-<component>:local`, `pullPolicy: Never`,
`pullSecret: false`, an empty `commit`, and a `configDigest` equal to the image ID Kubernetes reports for the running Pod (a `sha256:` config digest, which is what
the rollback verifies against). The `recommendation-agent` entry uses the recommendation-service image. Entries with `kind: registry` are written by the deploy job itself
(image `<registry>/<component>@sha256:<digest>`, `pullPolicy: IfNotPresent`, `pullSecret: true`). Do not edit `cd-state` in normal operation; the one documented manual
change is resetting a stuck lock (above).

## Production validation record

First checked on master commit `2b79df8` (pipeline #245532), always with `CD_AUTO_DEPLOY` unset:

| Step | Result |
|---|---|
| `deploy:production`, `DEPLOY_COMPONENTS=frontend` | passed in 50 s; the frontend moved from the local image to its registry digest |
| `deploy:rollback` | passed in 30 s; only the frontend was restored (local image, `imagePullPolicy: Never`, pull secret removed) |
| `deploy:production`, `DEPLOY_COMPONENTS=all` (retried with modified values) | passed in 1 min 57 s; movie, user, recommendation (+ agent CronJob), proxy and frontend run their published digests; Qwen, Secrets, databases and PVCs unchanged |

After each deployment the Pods' `imageID` equalled the published registry manifest digest; after the rollback it equalled the original
legacy image's config digest (local images report a config digest, not a registry digest). After each run `cd-state` was `idle` and
matched the live images, and the CronJob schedule, `suspend`, concurrency policy and `AGENT_MAX_QUEUED` were unchanged.

**No-op deployment.** A master commit that changes no component source (`app/frontend`, `app/proxy`, `app/backend/<service>` and
`app/backend/common`) still builds and publishes all six images, but `deploy:production` must report `nothing to deploy`: no lock, no
patch, no restart, `cd-state` untouched. Components are compared by source, not by image digest, because every commit produces new digests.

**Known interruption.** Every Deployment has one replica, so replacing the proxy or the frontend can return a few HTTP 502 responses (or
one timed-out request) for about 2 to 5 seconds while traffic moves to the new Pod. This was seen once in the frontend deployment and once
in the full deployment (proxy, then frontend), and not during the rollback. It is expected; it is not a failed deployment.

**Manual no-op test (pipeline #245667, commit `935353b`).** The commit changed only this README. `deploy:dry-run` and the manually played
`deploy:production` (job #327080) both reported every component as `sources unchanged: skip` and then `nothing to deploy`. A Kubernetes
snapshot taken before and after the job was identical across 56 lines: no Deployment, Pod, CronJob or `cd-state` change.

**Automatic mode.** `CD_AUTO_DEPLOY=true` and `CD_COMPONENTS=all` are configured as protected CI/CD variables, so `deploy:production` starts by itself
after `deploy:dry-run` on every master push. Pipeline #245690 (commit `7228c4f`, documentation-only) verified this path: `deploy:production`
(job #327277) started without a manual action, reported all five components as `sources unchanged: skip` and then `nothing to deploy`, and a Kubernetes
snapshot before and after was identical (56 lines). An automatic deployment of a real source change has **not** been tested; the same deployment code
was exercised by the manual runs above.
