# GitLab UI steps for M3 (done by a Maintainer; no token is ever pasted into chat, Git or CI variables)

## A. Create the BUILD runner (project runner)
1. Project → Settings → CI/CD → Runners → **New project runner**.
2. Tags: `g15-build`. **Run untagged jobs: OFF.** **Protected: ON** (runs only on protected branches). **Lock to current projects: ON**.
3. Maximum job timeout: 3600 s. Description: `g15-build (kaniko+skopeo, namespace g15-build)`. Create runner.
4. Copy the `glrt-...` token shown ONCE. Do not paste it anywhere except the hidden prompt of `sh load-runner-token.sh build`.

## B. Create the DEPLOY runner (project runner)
Same page, **New project runner**: tags `g15-deploy`, **untagged OFF**, **Protected ON**, **Lock ON**, timeout 1800 s.
Token goes only into the hidden prompt of `sh load-runner-token.sh deploy`.

## C. Create the registry READ-ONLY pull credential (for Kubernetes pulls)
Project → Settings → Repository → **Deploy tokens** → name `k8s-pull`, scope **read_registry only**, set an EXPIRY date (e.g. 90 days).
It is loaded later into TWO Secrets (`gitlab-registry` in g15-app, `gitlab-registry-read` in g15-cd) with the hidden-prompt script `sh load-pull-secrets.sh`.
Do NOT create or keep any write_registry deploy token: CI pushes with the per-job `CI_JOB_TOKEN`.

## D. Checks (answer yes/no in chat; no secrets)
1. Settings → CI/CD → General pipelines → "Limit access to this project" for the job token: pushes to this project's registry must be allowed.
2. Settings → CI/CD → Artifacts: maximum artifact size (we need ~60 MB for the Recommendation image archive, ~30 MB for the frontend).
3. Settings → Repository → Protected branches: `development` and `master` are protected, and who may merge/push.
4. Settings → Merge requests: approvals required for changes to `.gitlab-ci.yml` / `infra/ci-cd/**` (CODEOWNERS enforcement if the tier supports it).
5. Settings → CI/CD → Variables: confirm no registry/deploy secrets are stored there.
6. Old runner (g15-ci): leave exactly as is.

## E. Protected CI/CD variables
Settings > CI/CD > Variables, flag **Protected**: `CD_COMPONENTS` = `all` and `CD_AUTO_DEPLOY` = `true` (leave `CD_AUTO_DEPLOY` unset for manual deployment).
