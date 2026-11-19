# Application stack (`feat(k8s): deploy application stack`)

Deploys the five-component application (Angular frontend, Nginx proxy,
three Flask services, three dedicated PostgreSQL databases) onto the
self-hosted kubeadm cluster. No managed services, no imperative
`kubectl run` steps.

These manifests describe the **initial install** (local `g15-*:local` images, `imagePullPolicy: Never`). After the GitLab CD pipeline has taken over a
component, its image is an immutable registry digest set by the pipeline; reapplying this kustomization would reset it to the local image, which the deployment
job reports as drift (see `../../ci-cd/README.md`).

## Prerequisites

- Cluster from `infra/terraform` + `infra/ansible` is `Ready`.
- `kubectl` speaking to it (`KUBECONFIG=infra/terraform/cluster/kubeconfig.out`).
- Docker on this host (image builds).
- `db-passwords.env` present (gitignored):
  `cp db-passwords.env.example db-passwords.env` and set real values.
  Set `RECOMMENDATION_API_TOKEN` too; User and Recommendation use the same
  secret for their internal requests. When updating an older deployment,
  add this key to its existing env file without changing DB passwords.
- The service-to-service "agent context" token (`AGENT_CONTEXT_TOKEN`, used by
  Recommendation to read user context from User) lives in its **own** Secret,
  `g15-agent-context`, so the database credentials in `g15-db-passwords` are never
  touched. Both Deployments read the same value from it with `secretKeyRef`.
  **This Secret must be provisioned separately, before applying these Deployments:**
  it is not part of the kustomization (nothing here creates, updates or deletes
  it), and without it the new Pods stay in `CreateContainerConfigError` while the
  old ones keep serving. Create it once, without printing the value (no trailing
  newline, the services compare it byte for byte):
  `openssl rand -hex 32 | tr -d '\n' | kubectl -n g15-app create secret generic
  g15-agent-context --from-file=AGENT_CONTEXT_TOKEN=/dev/stdin`. Restart User and
  Recommendation after changing it: the value is read at start. Never commit the
  value.

## Storage

PVCs use `storageClassName: local-path`. Install the provisioner once:

```sh
kubectl apply -f https://raw.githubusercontent.com/rancher/local-path-provisioner/v0.0.31/deploy/local-path-storage.yaml
```

The nodes in this environment cannot reach `registry-1.docker.io`, so any
image they cannot pull must be side-loaded (same tarball flow as below).
This currently applies to the provisioner and PostgreSQL images.

Limitation (honest): one local-path PVC per database survives Pod
restarts but is not backup, replication, or all-VM-shutdown persistence.
That is a separate advanced-component decision.

Movie posters use the `movie-posters` local-path PVC (2 GiB requested),
mounted at `/srv/movie-service/assets/posters`. Run ingestion against this
same directory so the app can serve imported posters after pod restarts.
This volume has the same node-local storage and backup limitations.

## 1. Build images (repository root)

```sh
docker build -f app/backend/movie-service/Dockerfile -t g15-movie-service:local .
docker build -f app/backend/recommendation-service/Dockerfile -t g15-recommendation-service:local .
docker build -f app/backend/user-service/Dockerfile -t g15-user-service:local .
docker build -f app/frontend/Dockerfile -t g15-frontend:local .
docker build -f app/proxy/Dockerfile -t g15-proxy:local .
```

Backend images use gunicorn (never the Flask dev server); the frontend
image builds with Node 24 and serves static files from nginx. Backends run
a single worker with threads (`--workers 1 --threads 4`) so the in-process
Prometheus counters stay correct, and expose `/metrics` alongside `/health`
(see `g15_common.monitoring.metrics`). Monitoring (Prometheus, Grafana, ServiceMonitor,
dashboard) is owned by the Terraform app layer: `k8s/monitoring/README.md`.

## 2. Distribute images (no registry)

Initial install only. Afterwards the CD pipeline publishes the images to the GitLab Container Registry and the nodes pull them by digest.

```sh
docker save -o /tmp/g15-images.tar \
  g15-movie-service:local g15-recommendation-service:local \
  g15-user-service:local g15-frontend:local g15-proxy:local \
  rancher/local-path-provisioner:v0.0.31 postgres:18-alpine busybox:latest
for ip in <CP_IP> <WORKER1_IP> <WORKER2_IP>; do
  scp -i ~/.ssh/id_ed25519 /tmp/g15-images.tar "ubuntu@$ip:/tmp/g15-images.tar"
done
ansible -i ../ansible/inventory.ini kubernetes -b \
  -a 'ctr -n k8s.io images import /tmp/g15-images.tar'
```

Deployments use `imagePullPolicy: Never`.

On GCE the same flow carries only the five `:local` images; nodes pull
everything upstream natively (full egress), so no provisioner/Postgres/
monitoring side-loading is needed there. See `infra/README.md`.

## 3. Deploy

Namespaces (`g15-app`, `g15-monitoring`, `ingress-nginx`) and the
monitoring/logging/ingress releases are owned by Terraform:

```sh
terraform -chdir=infra/terraform/app apply
```

Then the application manifests (ordering handled by readiness probes):

```sh
kubectl apply -k infra/k8s/app
```

For the operator-only HTTP demo on port 30080, use:

```sh
kubectl apply -k infra/k8s/overlays/demo
```

The demo overlay disables the secure flag on the login cookie so browsers
can use it over HTTP. The base keeps the application's secure-cookie
default; public access needs HTTPS. Backend service URLs use Kubernetes
DNS names, so cross-service requests stay inside the cluster.

Ordering is handled by readiness probes, not sleeps: backends stay
unready (`/health` → 503) until their database is up.

## 4. Verify through the entrypoint

ingress-nginx is the only NodePort (`:30080` on any node); it forwards
through the proxy Ingress to the proxy ClusterIP (`/` and `/api/*` routing
lives in the proxy):

```sh
NODE=<any node IP>
curl "http://$NODE:30080/api/movie/health"
curl "http://$NODE:30080/api/recommendation/health"
curl "http://$NODE:30080/api/user/health"
curl -s "http://$NODE:30080/" | head -c 200
kubectl -n g15-app get pods,svc,pvc
```

## Conventions

- One dedicated PostgreSQL StatefulSet per service; services never touch
  another service's database.
- Secrets (`g15-db-passwords`, via `secretGenerator` + gitignored
  `db-passwords.env`) hold passwords only; hostnames/users/names live in
  the `g15-app-config` ConfigMap. `DATABASE_URL` is composed inside the
  container spec with Kubernetes `$(VAR)` expansion.
- `/health` is the readiness probe; liveness is TCP (backends) or `/`
  (frontend/proxy) so a temporary DB outage removes Pods from rotation
  instead of restart-looping them.
- The Qwen inference server (`inference/`) is a cluster-internal llama.cpp
  Deployment (`Service/inference`, ClusterIP 4210, no Ingress or NodePort) running
  Qwen2.5-0.5B-Instruct Q4_K_M on CPU with one slot. Only the Recommendation
  Service may reach it (`NetworkPolicy/inference-only-from-recommendation`). The
  model (~0.5 GB) is downloaded once from Hugging Face into the `inference-models`
  volume (local-path, node-local: it is only a cache, so losing it costs one
  re-download). The llama.cpp image is pulled by digest from `ghcr.io`, not
  side-loaded; pull it once at a quiet moment, because unpacking it briefly
  spikes node memory and CPU. The Recommendation Service reaches it through
  `INFERENCE_SERVICE_URL`; if it is down or too slow, generations fall back to the
  deterministic ranking. To switch it off without a rebuild, scale it to 0 or
  remove `INFERENCE_SERVICE_URL`.
- The background agent runs as the CronJob `recommendation-agent` (`agent/cronjob.yaml`), which ships
  **suspended** (`spec.suspend: true`) and reuses the Recommendation Service image (`flask agent-scan`).
  A scan only queues `source='auto'` generations; the Recommendation Service worker executes them, and with
  `AUTO_INFERENCE_ENABLED=false` they use the deterministic selection (`outcome=deterministic`), so the agent
  never calls the inference server (its Pods do not carry the `app=recommendation-service` label that the
  NetworkPolicy allows).
  - Throughput: a scan queues at most `AGENT_MAX_QUEUED=4` users (the queue holds `GENERATION_MAX_QUEUED=5`, so a
    user-requested job always finds a slot) and every 3 minutes: at most 80 users per hour, enough for about 1,000
    users on the 24 h refresh. A deterministic job takes about 2 s, and user-requested jobs are claimed first.
  - Controlled test (one authorized user, before activation): queue one automatic job for that user only, with the
    same call the agent makes, from the running Recommendation Pod:
    `kubectl -n g15-app exec deploy/recommendation-service -- python -c "import os; from services import jobs, pipeline; print(jobs.submit(os.environ['DATABASE_URL'], '<USER_UUID>', 'auto', pipeline.normalize_criteria(None, None), 1)['id'])"`
    Then check `generation_jobs`: `status=succeeded`, `outcome=deterministic`, `used_fallback=false`, one
    `recommendations` set with `source='auto'`, and no new inference request in `kubectl logs deploy/inference`.
  - Activation: apply only this file (`kubectl -n g15-app apply -f infra/k8s/app/agent/cronjob.yaml`), run one scan by
    hand (`kubectl -n g15-app create job --from=cronjob/recommendation-agent agent-first-scan`, expect at most 4 jobs),
    then `kubectl -n g15-app patch cronjob recommendation-agent -p '{"spec":{"suspend":false}}'`. To stop it, patch
    `suspend` back to `true`; queued auto jobs finish or can be left to drain.
