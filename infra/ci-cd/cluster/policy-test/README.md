# Admission policy tests (offline)
Inputs (not committed, large): `kubectl get --raw /openapi/v3/apis/apps/v1 > openapi-apps.json` (also `apis/batch/v1` -> `openapi-batch.json`,
`api/v1` -> `openapi-core.json`) and the live objects `live-deployments.json` / `live-cronjob.json`.
`python3 gen-policy.py` writes `30-deployer-admission-policy.yaml`; `python3 gen-cases.py` writes `cases.json` (hand-written cases plus a mutation
test of EVERY schema field); `python3 check-coverage.py` fails when the schema has a field the policy does not cover (run after every
Kubernetes upgrade); the CEL engine check is `harness/main.go` (cel-go): `go mod init policytest; go get github.com/google/cel-go@v0.22.1 gopkg.in/yaml.v3; go run .`
