# Recommendation latency: small sequential experiment (main GCP deployment)

Run on 2026-10-19, 17:41-18:16 UTC. Not a load test: one request at a time, 14 requests in total. Separate from Ricardo's HTTP load tests.

## Scope and conditions
- Deployment, model, resources, prompts, candidate selection and agent configuration unchanged. `AUTO_INFERENCE_ENABLED=false` (not enabled).
- Preconditions checked before starting: cd-state `idle` (resourceVersion 368310), no rollout in progress, no queued/running generation job, inference idle.
- One disposable test account created through the normal registration API, profile private, history fixed to 5 watched movies (`raw/fixed_profile.json`). No other user's data touched. Credentials and cookie stay outside this folder.
- Each request started 25-60 s after a `*/3` agent scan so deterministic automatic jobs do not overlap (queue wait 0.03-0.07 s in all 14 runs).
- Post-experiment check: cd-state unchanged, deployment generations unchanged, inference Pod 0 restarts, Ready.

## Versions and settings (`raw/environment.json`)
- recommendation-service `sha256:fb37c74d...`, user-service `sha256:9e8d4755...`, movie-service `sha256:609dc022...`, inference `ghcr.io/ggml-org/llama.cpp@sha256:6d607629...` (build b11277-eae11d221). Deployed commit recorded in cd-state: `2b79df8`.
- Model `Qwen/Qwen2.5-0.5B-Instruct-GGUF:Q4_K_M`, `n_params` 630,167,424, `--ctx-size 8192 --parallel 1 --threads 2`, app sends `temperature` 0.2 with a strict JSON schema, `INFERENCE_SYNOPSIS_CHARS=0`, timeouts 300 s / 150 s.
- Inference container: request 500m / 1 GiB, limit 1500m (`cpu.max 150000 100000`) / 1.5 GiB, on g15-worker1 (Intel Xeon 2.2 GHz, 2 vCPU = 1 core x 2 threads).

## Criteria
- M1-M7 (as requested, interleaved): `{count:5}` (broad, 4,995 eligible, 30 sent to the LLM) x3; `{count:5, genres:[Action], duration:epic}` (11 eligible = 11 sent) x3; `{count:20}` (40 sent) x1.
- Observed during the run: M3-M6 reused llama.cpp's prompt cache (1 token evaluated). Interleaving did not prevent it. Therefore S1-S7 were added with different broad/narrow filters (`plan_supplementary.json`): 3 broad, 3 narrow, 1 for 20 results.
- "Actual candidate count" = eligible movies and the pool size computed with the application's own `hard_filter` and `pool_size` on the live catalogue (5,000 movies, 5 excluded as watched); it was not read from the prompt.

## Results
See `results_tables.md` (all 14 requests) and `raw/` (per-run JSON with job row, llama.cpp log slice, cgroup counters before/after, poll trace).

| case | n | job time s, median (range) | prompt tokens evaluated | prompt tok/s |
|---|---|---|---|---|
| broad, 5 results, cold prompt | 4 | 63.0 (57.7-68.5) | 1,956 (1,740-2,114) | 32.6 (32.0-32.8) |
| narrow, 5 results, cold prompt | 4 | 26.4 (24.8-29.5) | 820 (770-927) | 34.8 (34.8-35.0) |
| 20 results (prefix mostly cached) | 2 | 34.5 (34.1-34.9) | 702 (693-711) | 27.7 (27.4-28.0) |
| identical prompt repeated (cached) | 4 | 3.2 (3.0-3.7) | 1 | n/a |

Requested seven runs only: broad5 68.5 / 3.7 / 3.4 s (median 3.7), narrow5 25.5 / 3.0 / 3.1 s (median 3.1), broad20 34.9 s (n=1).

- All 14 requests: outcome `llm`, 1 attempt, no fallback, no validation failure, requested count returned. No timeout.
- Generated tokens: 14 (5 results), 55 (20 results); generation 1.3-1.9 s and 7.1-7.4 s (about 7-10 tok/s).
- Combined non-inference overhead (job time minus llama.cpp total): 1.4-1.9 s in every run.
- Cold runs: the container used about 1.4 CPU on average (limit 1.5) and was throttled in 74-80% of the 100 ms periods, 9-14% of wall time (throttled s / job s).
- Memory of the inference container rose from 763 MB to 892 MB across the 14 requests (limit 1.61 GB, no OOM).
- API completion time minus job time: 0.4-1.4 s. Browser-visible latency was not measured; the frontend polls every 3 s, so an estimate is job time plus up to about 3 s.

## Limitations
- n=4 cold samples per main case; cold broad20 was not measured (both 20-result runs reused a cached prefix of about 2.2k tokens), so a fully cold 20-result request is an extrapolation (about 85-90 s, estimate).
- Single node, single model, one disposable profile with 5 watched movies, whose ranking determines the candidates; other profiles produce different candidate lists, not different prompt sizes.
- Per-request cgroup deltas include 1-3 s of ssh overhead at each end; they distinguish the request from the lifetime counters but are not exact.
- The cached/not-cached split rests on llama.cpp's reported `n_tokens` and evaluated tokens; the cache mechanism (a host-memory prompt cache) is inferred from the log, not read from the server's configuration.

## Files
`run_experiment.py` (script), `plan.json`, `plan_supplementary.json`, `make_tables.py`, `results_tables.md`, `run_main.log`, `run.log`, `raw/`.
