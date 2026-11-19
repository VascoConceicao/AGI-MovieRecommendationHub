# Recommendation Service

Flask 3.1 on Python 3.12. `main:create_app` creates the application; it provides health checks and recommendation persistence endpoints.

This component's `db/compose.yaml` owns its database and volume. Run `sh scripts/database/run-db.sh` from this directory to start its database using this service's `.env`. The root Compose file includes this same definition for combined startup.

This service owns one dedicated database running PostgreSQL 18. From the repository root, `scripts/development/run-backend.sh recommendation` loads the local database configuration and serves on `http://127.0.0.1:4207`. Docker is used only for the database.

The health endpoint runs `db/sql/health.sql` against this service's database. It returns HTTP 200 with `status: ok` and `database: up` only after `SELECT 1` succeeds; missing configuration or connection/query failure returns HTTP 503 with `status: unavailable` and `database: down`. Both responses identify `recommendation-service` and disable caching. Connection timeout is 3 seconds; statement timeout is 2 seconds. This is database readiness, not a liveness probe.

This service owns `requirements.txt`, its fully resolved `requirements.lock`, and `.venv`. Install it as documented in the root README. The shared package only supplies utilities; connections and SQL remain service-owned.

`api/` handles HTTP; `services/` contains logic and adapters; `helpers/` owns HTTP guards, validation helpers and response helpers; `models/` is reserved. `db/migrations/001_recommendations.sql` owns recommendation storage. No inference or ingestion is implemented. Martim's inference engine must remain behind a Recommendation Service adapter; its protocol and request/response schema need to be agreed before product implementation.

## API docs

Swagger UI: `/static/swagger.html`. OpenAPI file: `static/swagger.json`.
Through the local proxy: `http://127.0.0.1:4205/api/recommendation/static/swagger.html`.
The UI uses pinned Swagger UI CDN assets; internet is needed for the viewer.
Update selected services/endpoints with the `project` plugin’s `swagger` skill; `all` updates every service.


## Agent integration contract

This service exposes data APIs only. Your teammate owns the agent, prompt generation, LLM calls, recency weighting and background scheduling. There is no agent URL, outgoing agent call, request queue or request-table polling.

Keep Recommendation DB for **results** so the frontend can load both background and user-requested recommendations. Filter submission does not store requests. Older development installs may still have the unused `recommendation_requests` table; no new writes use it, new installs do not create it, and clear-all still clears legacy rows.

All endpoints below require `Authorization: Bearer <RECOMMENDATION_API_TOKEN>`. Through the proxy, prefix paths with `/api/recommendation`. Browser clients instead use User Service `/api/user/profile/...`, which supplies the signed-in user's ID and keeps service tokens private.

### Submit filters (Context API)

`GET /recommendation-filters` returns catalog choices, duration presets, year bounds and counts.

`POST /context/recommendation-requests` validates and returns data for the teammate's integration; HTTP 200 means filters are valid, not that an agent ran. Nothing is saved or dispatched.

```json
{
  "user_id": "USER_UUID",
  "filters": {
    "genres": ["Drama"], "languages": ["en"],
    "actors": ["Actor name"], "directors": ["Director name"],
    "year_from": 2000, "year_to": 2025,
    "duration": "medium", "count": 10
  }
}
```

Response: `{ "user_id": "USER_UUID", "source": "user_requested", "filters": { ...normalized filters... }, "generation_available": false }`.

Genres/languages must be current catalog values, up to 10 each. Actor/director names are free text, up to 10 names of 1–200 characters, trimmed and deduplicated. Year bounds are optional, 1888 through current year + 5. Counts: 5/10/15/20 (default 10). Duration: any, short (<90 min), medium (90–120), long (121–180), epic (>180). Omitted filters have no constraint except count defaults. Values within one field are alternatives; separate fields constrain the same request. Invalid data returns 400; unavailable catalog returns 503.

### Context API

Agent-facing endpoints live in Recommendation Service, grouped under **Context API** in Swagger. Prefix `/api/recommendation` through the proxy and use `Authorization: Bearer <RECOMMENDATION_API_TOKEN>`. Internally, this service uses `USER_SERVICE_URL` and the shared private `AGENT_CONTEXT_TOKEN` to read User Service APIs; User DB access stays in User Service.

- `GET /context/users?limit=100&after=UUID`: user IDs only, with `next_cursor`; omit after for first page. Limit 1–1000. This lets a background agent discover users without account credentials.
- `GET /context/users/USER_UUID?limit=100&watched_offset=0&watchlist_offset=0`: returns `user_id`, `as_of`, and independent `watched` / `watchlist` pages with `items`, `total`, `offset`, `limit`, `next_offset`.
- Watched items: `movie_id`, nullable `watched_at`, `recorded_at`.
- Watchlist items: `movie_id`, `added_at`.

Timestamps are ISO 8601. `watched_at: null` means unknown; `recorded_at` is when history was stored, not proof of when the movie was watched. Imported records may share import timestamps. Watched ordering uses watched_at when known, otherwise recorded_at; watchlist ordering uses added_at, newest first. The agent decides recency weighting. Each response is a consistent snapshot; data can change between pages. Missing user returns 404. No email, password or sessions are exposed.

Get movie details through Movie Service `GET /movies?ids=UUID,UUID` (max 50 IDs per call), prefixed `/api/movie` through proxy. Services never read each other's DBs.

#### Example responses

Synthetic IDs, no real user data. Both examples request `limit=2`.

`GET /api/recommendation/context/users?limit=2` → `200`:

```json
{
  "user_ids": [
    "11111111-1111-4111-8111-111111111111",
    "22222222-2222-4222-8222-222222222222"
  ],
  "next_cursor": "22222222-2222-4222-8222-222222222222"
}
```

Use `next_cursor` as `after` for the next page; null means done.

`GET /api/recommendation/context/users/11111111-1111-4111-8111-111111111111?limit=2` → `200`:

```json
{
  "user_id": "11111111-1111-4111-8111-111111111111",
  "as_of": "2026-10-09T16:00:00+00:00",
  "watched": {
    "items": [
      {
        "movie_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        "watched_at": "2026-10-08T20:30:00+00:00",
        "recorded_at": "2026-10-08T20:35:00+00:00"
      },
      {
        "movie_id": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
        "watched_at": null,
        "recorded_at": "2026-10-01T10:00:00+00:00"
      }
    ],
    "total": 3,
    "offset": 0,
    "limit": 2,
    "next_offset": 2
  },
  "watchlist": {
    "items": [
      {
        "movie_id": "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
        "added_at": "2026-10-09T12:00:00+00:00"
      }
    ],
    "total": 1,
    "offset": 0,
    "limit": 2,
    "next_offset": null
  }
}
```

Here watched history has another page (`watched_offset=2`); watchlist is complete. `watched_at: null` means the actual watch date is unknown. Empty collections have `items: []`, `total: 0`, and `next_offset: null`.

### Save results and read them in the frontend

`POST /recommendations`:

```json
{ "user_id": "USER_UUID", "movie_id": "MOVIE_UUID", "reason": "Why this movie", "score": 0.8, "source": "auto" }
```

`source` is required: `auto` for background recommendations, `user_requested` for filter-driven results. Score is optional (0–1). User/movie IDs must be resolved by the caller; existence checks are not performed here. A user/movie/source pair is unique; repeated writes update the result. The same movie can appear under both sources. Records include created_at and updated_at; migrations preserve old records as auto.

`GET /recommendations?user_id=UUID&source=all&offset=0&limit=25` returns items and total. Source may be all/auto/user_requested; results sort score descending then creation time. With `source=all` each movie appears **once**: when both sources recommend it, the `user_requested` row (and its reason) is shown. `total` and pagination count the deduplicated list, and the User Service title search pages through the same listing so it agrees. The stored rows are never changed; `auto` and `user_requested` listings are unchanged. `DELETE /recommendations/UUID` is idempotent.

The frontend Recommendations page uses two tabs, Recommended for You (`source=auto`) and My Recommendations (`source=user_requested`), through authenticated `GET /profile/recommendations`; the `all` source remains available in the API but the page no longer uses it. Reopening the tab reloads results. No background polling is added.

### Asynchronous generation

Generation runs the whole pipeline (user context, catalog, candidates, LLM selection with deterministic fallback, atomic persistence), which can take over a minute on CPU, so the API never waits for it. Both endpoints use the same `Authorization: Bearer <RECOMMENDATION_API_TOKEN>` as the rest of this service.

`POST /recommendations/generate` with `{ "user_id": "USER_UUID", "filters": { ... }, "count": 10 }` (`filters` and `count` optional; same filter contract and counts 5/10/15/20, default 10; `source` may be omitted and only `user_requested` is accepted) returns **202** `{ "job_id": "...", "status": "queued" }` immediately. Errors: **400** invalid input (nothing is queued), **409** a generation is already queued or running for this user and source (body has that job's `job_id` and `status`; a different `filters`/`count` does not replace it), **503** with `Retry-After` when the bounded queue is full or the database is unavailable.

`GET /recommendations/generations/JOB_UUID?user_id=USER_UUID` returns `status` `queued`, `running`, `succeeded` or `failed`, plus `source`, `requested_count` and timestamps. `succeeded` adds `recommendation_count`, `outcome` (`llm`, `llm_after_retry`, `fallback_inference_error`, `fallback_validation_error`, `no_candidates`), `attempts`, `used_fallback`, `fallback_reason`, `duration_seconds`; deterministic fallback and no eligible movies are successes. `failed` adds a safe `error` category: `user_service_unavailable`, `user_not_found`, `movie_catalog_unavailable`, `invalid_request` (for example a genre the catalog does not offer), `database_error`, `internal_error` or `interrupted`. A job of another user, or an unknown id, is **404**. When a job succeeds, read the results with the existing `GET /recommendations`; while it is queued or running that endpoint keeps returning the previous set, and a failed job never changes it.

Design and limits: job state lives in the `generation_jobs` table, so it is shared by processes and survives restarts. One worker thread per serving process claims jobs; the number of jobs running at once is capped across all processes in PostgreSQL (`GENERATION_MAX_RUNNING`, default 1 to match llama.cpp `--parallel 1`) and at most `GENERATION_MAX_QUEUED` (default 5) wait. A running job is kept alive by a heartbeat; if its process dies, any process marks it `failed` with `interrupted` after about 60 seconds. It is **not retried**, and shutdown does not wait for a job in flight. The worker starts with the first HTTP request of a serving process (never in CLI commands); `GENERATION_WORKER=false` disables it. `failed` / `interrupted` therefore means *outcome unknown*, not *nothing changed*: `replace_set` is atomic (a set is never partially replaced), but it commits before the job is marked `succeeded`. A crash in that window, or a heartbeat stall that gets a still-running job declared interrupted (its late result is then ignored, and a second generation for the same user and source may be accepted meanwhile; `replace_set` serializes them and the last commit wins), can leave the new set stored while the job reads `failed`. A failure with another category normally happened before persisting (and `replace_set` rolls back on its own errors), so the previous set is unchanged; the only exception would be a bug after the commit. Clients should read `GET /recommendations` after any terminal state instead of inferring its content from the job. Finished jobs are deleted after 7 days. Migration `004_generation_jobs.sql` is applied by `init-db`, which `scripts/development/run.sh` and the container's `start.sh` run before serving; restart the service to pick up the new table and routes.

#### User Service gateway integration

The browser never holds `RECOMMENDATION_API_TOKEN`: it stays in the User Service environment, nginx's `/api/recommendation/` route adds no credentials (keep it that way), and the frontend only calls `/api/user/profile/...` with its session. The User Service now provides the session-authenticated gateway `POST /profile/recommendation-generations` and `GET /profile/recommendation-generations/<job_id>`: it takes the user from the session (never from the request), forwards to the two endpoints above, and passes through `202`, `400`, `404`, `409` (with `job_id` and `status`) and `503` (with `Retry-After`). Contract and error table: [User Service README](../user-service/README.md#recommendation-generation-gateway). Results keep using `GET /profile/recommendations`.

### Proactive background agent

The agent makes recommendations ready before a user asks, so they are there at login: automatic sets are stored with `source = "auto"` and shown next to the user-requested ones. It is a one-shot command, scheduled from outside (cron or a Kubernetes CronJob), so no scheduler thread runs in any web worker or replica:

```sh
cd app/backend/recommendation-service
set -a; . ./.env; set +a
.venv/bin/python -m flask --app main:create_app agent-scan      # one scan; exit code 1 if the User Service could not list users
```

A scan lists users through the User Service `/internal/recommendation-users` API (paginated; nothing is scheduled unless the whole list was read), decides who needs a refresh, and **queues `auto` jobs on the same `generation_jobs` queue** used by user requests. It never calls Qwen or runs the pipeline itself: the Recommendation Service's own worker executes the jobs, so the service must be running for queued jobs to complete. A scan holds an advisory lock, so overlapping scans skip themselves, and duplicate protection per `(user_id, source)` still applies.

Policy (environment variables): a user is *fresh* when their latest successful `auto` generation (a `no_candidates` success counts) or their last write to the `auto` set is younger than `AGENT_REFRESH_HOURS` (default 24); a user whose latest `auto` job failed less than `AGENT_RETRY_COOLDOWN_MINUTES` (default 60) ago is skipped; everyone else is due. Users never generated come first, then the stalest. Only `auto` history is considered, and only the `auto` set is ever replaced. Freshness is time based: new watch activity does not trigger an earlier refresh.

Capacity: the agent stops queueing when `AGENT_MAX_QUEUED` jobs (default 2, out of `GENERATION_MAX_QUEUED`, default 5) are already waiting and leaves the remaining users for the next scan, so automatic work cannot fill the queue. Queued user requests are claimed before queued automatic jobs; an automatic job already running is not preempted, so a user request can wait for one inference. With a CPU Qwen taking about a minute per cold generation, schedule scans every few minutes (for example `*/5 * * * *`); each scan queues at most `AGENT_MAX_QUEUED` users. The summary line logged per scan reports users examined, scheduled, fresh, cooldown, active, deferred and errors.

Inference for automatic generations: with 1,000 users, asking a CPU-only LLM for every automatic generation is not practical (about a minute each). `AUTO_INFERENCE_ENABLED=false` makes jobs with `source = "auto"` use the deterministic selection directly (same ordering, scores and reasons as the fallback); user-requested jobs still use the LLM. Such jobs finish with `outcome = "deterministic"`, `attempts = 0`, `used_fallback = false` and `fallback_reason = "not_requested"` (it is not a failure, so there is no fallback warning). The default is `true`, which keeps every source on the LLM path.

Scheduling: with cron, run the command above from the service directory. With Kubernetes, use a `CronJob` with `concurrencyPolicy: Forbid`, the same image as the Recommendation Service Deployment, command `python -m flask --app main:create_app agent-scan`, and the `DATABASE_URL`, `USER_SERVICE_URL` and `AGENT_CONTEXT_TOKEN` values from that Deployment (the agent needs neither the Movie Service nor the inference URL).

### Inference engine (llama.cpp / Qwen)

The pipeline asks an OpenAI-compatible llama.cpp server, `POST {INFERENCE_SERVICE_URL}/v1/chat/completions`, to choose `count` candidate keys (strict JSON schema, temperature 0.2, no model field, no authentication); everything else is deterministic, and any transport failure or invalid answer falls back to the deterministic top-N. Environment variables (defaults keep the previous behaviour when absent):

| Variable | Default | Purpose |
|---|---|---|
| `INFERENCE_SERVICE_URL` | `http://127.0.0.1:4210` | Inference server base URL (`http://inference:4210` in Kubernetes) |
| `INFERENCE_TIMEOUT_SECONDS` | `120` | Socket timeout of the first call; CPU inference needs more (Kubernetes sets 300) |
| `INFERENCE_RETRY_TIMEOUT_SECONDS` | `60` | Socket timeout of the single retry (Kubernetes sets 150) |
| `INFERENCE_SYNOPSIS_CHARS` | `200` | Synopsis characters per candidate in the prompt; `0` leaves it out (Kubernetes sets 0) |
| `AUTO_INFERENCE_ENABLED` | `true` | `false`: background (`auto`) generations skip the LLM (see the agent section) |

Measured with Qwen2.5-0.5B Q4_K_M on one 2.2 GHz AVX2 core (2026-10-15 benchmark, 30 candidates, 10 requested): about 63 s without synopses (~2,100 prompt tokens) and 85 s with 80-character synopses (~2,700 tokens); pod memory below 900 MiB. All answers were valid, but the small model returns the first keys it is shown (the deterministic order), so the selection currently equals the deterministic ranking.

### Frontend integration (Angular → User Service → Recommendation Service)

```text
Angular → nginx (:4205) → User Service (session + X-G15-Request) → Recommendation Service (service token)
  POST /api/user/profile/recommendation-generations  → POST /recommendations/generate   → 202 {job_id}
  GET  /api/user/profile/recommendation-generations/<job_id> → GET /recommendations/generations/<job_id>?user_id=<session>
  GET  /api/user/profile/recommendations?source=auto|user_requested|all
generation_jobs queue → worker → pipeline → Qwen → recommendations table (replace_set)
```

The Profile → Recommendations page has two tabs, each showing a different real saved set (no mock data); a recommendation set is never shown in both:

| Section | Source | How it is filled | When it loads |
|---|---|---|---|
| **Recommended for You** (first tab) | `auto` | Only by the background agent (`flask agent-scan`, see above). Angular never generates it | On opening the page, every time (the component is recreated when you return to the sub-tab); a retry button on error; read-only, never triggers inference |
| **My Recommendations** (second tab, holds the Generate button) | `user_requested` | By the user: filter modal (genres, languages, actors, directors, years, duration, count 5/10/15/20) → real generation | Loaded when the tab is selected and again after every terminal job state (whichever list is showing is reloaded) |

After **Generate**, Angular posts the structured filters (it never builds a prompt) and receives a job id immediately. It then polls the job every 3 seconds, for at most 6 minutes (real Qwen takes 1–2 minutes when cold, plus any wait for the single inference slot): `queued` ("waiting its turn"), `running` (spinner and "our AI model is choosing recommendations"), `succeeded` (stops polling and reloads the saved list; a deterministic fallback adds a note, and zero candidates shows "No movies match these filters" instead of an error), `failed` (friendly message from the error category and the saved list is reloaded anyway). A `409` follows the already active job instead of starting another; a `503` shows the retry hint (`Retry-After`); the Generate button is disabled while a generation is starting or active. Leaving the sub-tab stops the polling (the job keeps running on the server); coming back reloads the saved results, and pressing Generate again follows the active job through the `409` path. Generating never changes the automatic set, and the two sets are stored independently per `(user_id, source)`. The generation status line belongs to the My Recommendations tab and is shown again when you return to it while a job is active.

Each card shows the title, the movie details, the deterministic reason and an "ordering score" (with its rank in the list). The score only orders a list; it is not a probability or an AI confidence.

**Known behaviors and limitations.** The page lists one source per tab, so the `all` source (deduplicated by movie, `user_requested` preferred) is no longer used by the frontend. A user who has never been scanned sees "Your personalized recommendations are being prepared. Check back soon!" until the agent runs (no generation is triggered at registration; that would need a new API contract). `generation_available` in `GET /recommendation-filters` still reads `false` and is not used by the frontend. The agent's freshness is time-based (24 hours by default).

**Environment.** User Service: `RECOMMENDATION_SERVICE_URL`, `RECOMMENDATION_API_TOKEN`, `AGENT_CONTEXT_TOKEN`, `MOVIE_SERVICE_URL`. Recommendation Service: `RECOMMENDATION_API_TOKEN` (same value as the User Service's), `AGENT_CONTEXT_TOKEN` (same value as the User Service's), `USER_SERVICE_URL`, `MOVIE_SERVICE_URL`, `INFERENCE_SERVICE_URL`, `DATABASE_URL`; optional `GENERATION_*` and `AGENT_*` described above.

**Is the running service using the latest code?** `flask run` and gunicorn load the code once at start, so a service started before a change keeps serving the old behaviour (for example duplicates in `source=all`) until it is restarted. Check the process start time against the last change, and restart if it is older:

```sh
# 4207 = Recommendation Service, 4208 = User Service (adjust the port)
ps -o pid,lstart,args -p "$(ss -ltnp | sed -n 's/.*:4207 .*pid=\([0-9]*\).*/\1/p')"
git log -1 --format='%h %cd' -- app/backend/recommendation-service   # last committed change
stat -c '%y' app/backend/recommendation-service/services/recommendations.py   # last edit on disk
```

If the process `lstart` is earlier than those times, stop it and start it again with its usual `run.sh` (never needed for frontend-only changes). A functional check for the listing deduplication: for a user with the same movie in both sets, `GET /recommendations?user_id=<id>&source=all&limit=100` (Bearer token) must return each `movie_id` once, with `total` equal to the number of distinct movies.

**Manual browser test (local).** Restart the Recommendation Service and the User Service so they load the new routes (their `run.sh` applies the migrations), keep Movie Service and the llama.cpp Qwen server running, and start the proxy and the frontend as usual (`http://127.0.0.1:4205`). Sign in, open Profile → Recommendations, open the **My Recommendations** tab, choose filters and press **Generate recommendations**: the button switches to "Generating…" with a status line, and the movies appear by themselves when the job finishes. Switch to another profile tab and back to confirm the saved results reload. Then open **Recommended for You** (first tab) to see the automatic set. To fill it safely, with the Recommendation Service running (its worker executes the job), run the agent once; it only queues a normal `auto` job for users whose automatic set is missing or older than 24 hours:

```sh
cd app/backend/recommendation-service
set -a; . ./.env; set +a
.venv/bin/python -m flask --app main:create_app agent-scan
```

Reload the Recommendations page after the job finishes (a few seconds to about two minutes with real Qwen); running the command again straight away schedules nothing because the result is fresh. Nothing is fabricated: with no automatic data the section shows its empty state.

`POST /admin/reset-recommendation-db` takes `{ "table": "all" }` or `recommendations`, using separate `RECOMMENDATION_RESET_TOKEN` with reset enabled. It clears results and any legacy stored requests. No ingestion task.

API layout: `api/` contains route handlers and registers blueprint hooks. `helpers/` contains authorization/session guards, request parsing helpers and response/cookie helpers. `services/` owns business logic, persistence and service adapters. Helper modules never import API modules.
