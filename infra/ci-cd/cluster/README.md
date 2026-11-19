# Cluster configuration for the CD runners (infrastructure as code)
Applied by hand with the admin kubeconfig (nothing here is read by a CI job). Order: `00` namespaces, `10` service accounts,
`20` RBAC for the deploy identity, `30` admission policies (generated from the live schema, see `policy-test/`), then the runners:
`sh render-runner.sh build|deploy | kubectl apply -f -` after `sh load-runner-token.sh build|deploy` (hidden prompt, token only via
stdin) and, for pulls, `sh load-pull-secrets.sh` (read_registry deploy token). `rbac-test.sh` and `policy-live-test.sh` run on the
control plane and change nothing (impersonation + `--dry-run=server`). `verify-published.sh` checks all six published images for
an exact commit (`EXPECTED_SHA=<40 hex> bash verify-published.sh`). `40-networkpolicies.yaml` is optional hardening, not applied.
`GITLAB-UI-STEPS.md` lists the GitLab settings. The ci-tools digest in `values-deploy.yaml` must equal the one in `../delivery.yml`.
The remaining one-time steps (protected CI/CD variables, the `cd-state` ConfigMap, activating the agent) are in `../README.md`. `load-runner-token.sh` and
`load-pull-secrets.sh` reach the control plane with `gcloud compute ssh g15-cp1 --zone=europe-southwest1-a --project=prefab-conquest-511709-j5`; edit that line for another
Google Cloud project or zone.
