# Load tests and recommendation-latency experiment

Two separate experiments back the report's Evaluation section. They answer different questions and ran on **different clusters**, so they must not be compared.

| Experiment | Where | Question | Data |
|---|---|---|---|
| HTTP load study (16 Oct 2026) | a separate three-VM Google Cloud cluster (not the main deployment) | How do throughput and latency of the HTTP entry point change with client concurrency? | `results/load-2026-10-16.json` (raw driver output) |
| Recommendation latency (19 Oct 2026) | the main deployment | What does one LLM-backed recommendation cost, and where does the time go? | `latency/` |

## 1. HTTP load study

`run-health-load.py` is a standard-library Python driver (k6 could not be installed in the test environment). Each step holds a constant number of virtual users (VUs); each VU loops over five random paths (`/api/movie/health`, `/api/recommendation/health`, `/api/user/health`, `/api/movie/movies?limit=5`, `/`) with 0.2 s think time and a 10 s client timeout. No AI inference is exercised.

```sh
# 50 VUs for 60 s, 100 for 120 s, 200 for 90 s, then 30 s without load
python3 infra/load/run-health-load.py http://<node>:30080 > infra/load/results/load-<date>.json

# the report's figure, regenerated from the raw JSON (needs matplotlib)
python3 infra/load/make-loadfig.py infra/load/results/load-2026-10-16.json docs/images/fig-load.png
```

`k6-health.js` declares the intended paths and thresholds (p95 < 500 ms, failures < 1 %). It is **not** an exact specification of the driver: k6 ramps the number of VUs linearly between stages, the Python driver holds it constant, and the driver adds the catalogue request. `load-report.py` wraps the driver (same workload and metrics) and prints a live table; it was used for the run shown in the demonstration video.

Results of the 16 Oct study (24,671 requests, one run per step):

| VUs | Requests | req/s | 2xx/s | 2xx (%) | 502 | Timeouts | p50 | p95 |
|---|---|---|---|---|---|---|---|---|
| 50 | 3,206 | 53.4 | 52.5 | 98.3 | 15 | 40 | 133 ms | 1.66 s |
| 100 | 6,560 | 54.7 | 52.8 | 96.6 | 51 | 175 | 165 ms | 4.05 s |
| 200 | 14,905 | 165.6 | 21.4 | 12.9 | 12,116 | 862 | 364 ms | 10.0 s (client timeout) |

Successful throughput was already saturated at about 53 requests/s with 50 VUs, so the saturation point lies at or below 50 VUs and was not located; the declared target was not met at any step. 2xx/s is the number of successful responses divided by the nominal step duration. The p95 at 200 VUs equals the client timeout, so it is a lower bound; all percentiles include failed requests.

### What this study does not show
- It does not identify the bottleneck. Each backend runs one gunicorn worker with four threads (`--workers 1 --threads 4`) and the Nginx proxy one worker with 256 connections, so limited request concurrency is a plausible cause, but per-component saturation and the origin of the 502 responses were not measured.
- No metrics or logs were archived. The operator reports no pod restarts and no application-level 5xx responses during the study; this cannot be confirmed from the repository.
- The test cluster, which was fresh with an empty movie catalogue, is not the main deployment. The results describe that environment only.
- One run per step, from a single Python process that opens a new connection per request; the client may itself limit the offered load.

See `results/README.md` for the provenance of each result file.

## 2. Recommendation latency on the main deployment

A small sequential experiment (14 user-requested generations, one at a time, no concurrent load, on a disposable account with a fixed profile). Procedure, versions, results and limitations are in [`latency/SUMMARY.md`](latency/SUMMARY.md); the per-request table is `latency/results_tables.md`; `latency/raw/` holds the sanitised per-run measurements.

Headline: latency is dominated by prompt evaluation on CPU (about 33 tokens/s). Requests with 30 candidate movies took 58-69 s (median 63 s, n = 4), requests with 11-13 candidates 25-30 s (median 26 s, n = 4), and a repeated identical prompt about 3 s because llama.cpp reused its cached prompt (it does not measure inference speed). All 14 requests completed through Qwen2.5-0.5B-Instruct without fallback or retry.

```sh
# requires cluster access and a disposable account; see latency/SUMMARY.md
python3 -I infra/load/latency/run_experiment.py env|setup|profile|scan|run <plan.json> [prefix]|report
```
