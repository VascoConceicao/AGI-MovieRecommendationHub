# User Service

Flask 3.1, Python 3.12, Psycopg 3, and Argon2id account authentication. This service alone accesses its dedicated PostgreSQL 18 User DB.

## Local startup

Install the service's `requirements.lock` into `.venv` and install the common package as described in the root README. Start its database with `sh scripts/database/run-db.sh`, then start the service with `sh scripts/development/run.sh`. The local launcher loads this service’s `.env`, creates the account schema transactionally without deleting data, and listens on `127.0.0.1:4208`. Local HTTP defaults `AUTH_COOKIE_SECURE=false`.

The container performs the same schema initialization before launching Gunicorn. Its default `AUTH_COOKIE_SECURE=true` requires HTTPS at the browser-facing proxy. Only explicitly disable it for an HTTP development/demo environment.

## Schema

`db/migrations/001_accounts.sql` creates the tables. `002_usernames.sql` adds unique usernames and backfills existing users without deleting accounts:

- `users`: UUID account ID, case-insensitively unique email and username, Argon2id password hash, creation/update timestamps.
- `user_profiles`: one profile per account, display name, optional bio, update timestamp.
- `user_sessions`: hashed opaque session token, account ID, creation and expiry timestamps.

Profile and session foreign keys cascade on account deletion. Registration creates account, profile, and initial session in one transaction. Email is trimmed and lowercased. Display names have 1–80 characters; passwords are required but have no character-count restriction, as requested by the user. The 16 KiB request-body limit still applies. Password confirmation is validated and never stored.

## HTTP API

The proxy maps `/api/user/` to this service's `/`. Authentication responses disable caching.

| Method | Service path | Behavior |
| --- | --- | --- |
| GET | `/health` | Database readiness; 200 if `SELECT 1` succeeds, otherwise 503. |
| POST | `/auth/register` | JSON `username`, `display_name`, `email`, `password`, `password_confirmation`; 201 with `user` and a session cookie. Duplicate email or username returns 409; invalid fields return 400. |
| POST | `/auth/login` | JSON `email`, `password`; 200 with `user` and a new session cookie; incorrect credentials return the same generic 401 message. |
| GET | `/auth/me` | Current account's `id`, `email`, `username`, `display_name`, and `avatar_id`; missing/expired session returns 401. This is a private account endpoint, not a public profile response. |
| POST | `/auth/logout` | Deletes the current session and clears its cookie; 200, including when already signed out. |

POST requests require `Content-Type: application/json` and `X-G15-Request: 1`. No CORS access is granted: foreign origins cannot supply this custom header without a rejected preflight. Explicit cross-site browser requests are rejected as well. Requests are limited to 16 KiB. Database failures produce a generic 503 response without exposing connection details.

Sessions expire after seven days and are revalidated in PostgreSQL on every authenticated request. The browser receives an HttpOnly, SameSite=Lax cookie scoped to `/api/user`, Secure by default outside the local launcher. Only SHA-256 hashes of random 256-bit session tokens are stored; no tokens are stored in browser local storage. Reauthentication rotates the browser's current session. Logout revokes it.

Manual schema initialization and expired-session cleanup, with `DATABASE_URL` set, are available from this directory:

```sh
.venv/bin/python -m flask --app main:create_app init-db
.venv/bin/python -m flask --app main:create_app clean-sessions
```

Run cleanup periodically in deployment. Login attempt throttling and password recovery remain future work. Movie data and generated recommendations stay in their owning services' databases.

## Account-table reset endpoint (opt-in)

`POST /admin/reset-user-db` is exposed through the proxy at `/api/user/admin/reset-user-db`. It clears table contents while keeping the schema. It is disabled by default and requires a separate bearer token, independent of normal user sessions.

To enable locally, add the following to this service's ignored `.env`, set a private token, then restart the User Service:

```dotenv
AUTH_RESET_ENABLED=true
AUTH_RESET_TOKEN=replace-with-your-private-reset-token
```

In Bruno use POST `http://127.0.0.1:4205/api/user/admin/reset-user-db`, `Content-Type: application/json`, and `Authorization: Bearer YOUR_RESET_TOKEN`. Set the `resetToken` Bruno variable to the same private value to use the saved examples in `app/backend/bruno-collection/DBs/Clear/User/`.

Clear all account tables:

```json
{"table": "all"}
```

Clear one selected table:

```json
{"table": "user_sessions"}
```

Allowed selections are `all`, `users`, `user_profiles`, and `user_sessions`. Selecting `users` also clears dependent profiles and sessions because of foreign-key cascades. Selecting `user_profiles` leaves account/password rows but removes their profiles; those accounts cannot sign in through the current profile-dependent login until profiles are restored. Selecting `user_sessions` signs everyone out while retaining accounts and profiles. Clearing all or users allows fresh registration with previously used emails.

The payload must contain exactly the `table` field. Missing/invalid selections return 400; missing/incorrect token returns 401; disabled or unconfigured resets return 404. Deletion is transactional and uses allowlisted SQL identifiers. Successful responses list affected tables and deleted row counts, for example:

```json
{"cleared_tables": ["user_sessions"], "deleted_rows": {"user_sessions": 3}}
```

## API docs

Swagger UI: `/static/swagger.html`. OpenAPI file: `static/swagger.json`.
Through the local proxy: `http://127.0.0.1:4205/api/user/static/swagger.html`.
The UI uses pinned Swagger UI CDN assets; internet is needed for the viewer.
Update selected services/endpoints with the `project` plugin’s `swagger` skill; `all` updates every service.

## Sample users

Run `sh app/backend/user-service/db/ingestion/users.sh` from the repo root to add 1,000 sample users plus admin, with profiles and no sessions. Use VS Code task `ingest: users` to choose the count. See [ingestion instructions](db/ingestion/README.md) for login details and options. Reruns skip existing users.

## Private profile and watched history

`GET /profile` returns the signed-in user's display name, bio, and `avatar_id`. `POST /profile/avatar` accepts `{"avatar_id":1}` (1–10), using the same session cookie and `X-G15-Request: 1` header as account mutations. Invalid selections return 400; signed-out requests return 401. New profiles get a random avatar from 1–10. Schema initialization preserves existing avatar selections. Public discovery follows the visibility rules below.

`GET /profile/watched?offset=0` returns `items`, `total`, `offset`, and `limit` (25). Each item has `movie_id`, optional `watched_at`, and `recorded_at`; newest recorded first with UUID tie-break. One row per user/movie. Unknown watched dates remain null. Movie details come from Movie Service through its API. Marking watched uses `/profile/watched/add`.

`watched_movies` belongs only to User DB, cascades on user deletion, and has no cross-database foreign key. User reset now accepts `watched_movies`; `all` and `users` include watched history. Clearing sessions alone keeps history. Coordination tables are deliberately retained.

`POST /internal/clear-watched` is for full catalog reset, not browser sessions. It requires the dedicated `WATCHED_CLEANUP_TOKEN` and JSON `operation_id` UUID plus `movie_ids` UUID array. Configure the same cleanup credential in Movie Service; admin reset tokens stay independent. The operation atomically clears history, retires deleted UUIDs, and records its deleted count. Repeated operation IDs return the original count without clearing newer records. `retired_movie_ids` and `watched_cleanup_operations` persist through normal account resets. A DB trigger serializes watched inserts/updates against cleanup and rejects retired movies. Each service still accesses only its own database.

## Live history updates

`GET /profile/events` is a session-authenticated SSE endpoint. Migration `004_watched_notifications.sql` sends PostgreSQL notifications on watched row inserts, updates, deletes, and table truncation. Direct SQL and future API writes both work; rolled-back changes send nothing. Only the affected user gets a `watched-changed` event (truncate affects all users). The browser reloads history on that event and on `ready` after initial connection/reconnect. No timed history polling or public refresh mutation endpoint.

The stream sends keep-alive comments and rechecks session validity at least every 20 seconds; comments never refresh history. Revoked/expired sessions get `signed-out` and close. Each stream uses one dedicated listening connection and thread, limited to 16 per process. The production launcher uses 32 threads to retain normal request capacity. Disconnects close listeners, and capacity overflow returns 503 for automatic reconnect. For larger deployments, replace per-client listeners with a shared fanout worker before increasing capacity.

Nginx disables buffering for this endpoint; Angular's development proxy streams it too. See [Psycopg notification guidance](https://www.psycopg.org/psycopg3/docs/advanced/async.html#asynchronous-notifications).

Watched history also returns `watch_minutes`, summed across all watched movies through Movie Service `/movies/duration` (batches of 1000). Set `MOVIE_SERVICE_URL` to the internal Movie Service address. No cross-service database reads. Zero for empty history; null for missing movies or unavailable duration data. Each unique watched movie contributes its full duration once.

Watchlist is user-owned in watchlist_movies. GET/POST /profile/watchlist reads or changes membership. POST /profile/watched/add marks watched and atomically removes watchlist membership. Watched movies cannot be added through the normal watchlist action. `POST /profile/watched/move-to-list` with `movie_id` explicitly moves a movie to My list: removes watched status and inserts watchlist membership in one transaction. Requires the session cookie and `X-G15-Request: 1`; retries are idempotent. User/all and Movie coordinated resets clear watchlists too.


### Recommendation APIs

Session-authenticated `GET /profile/recommendation-filters`, `POST /profile/recommendation-requests` and `GET /profile/recommendations?source=all|auto|user_requested&offset=0` proxy Recommendation Service. POST takes only `{ "filters": { ... } }`, requires `X-G15-Request: 1` and derives user ID from session. It returns validated filters only; no request is stored or agent called.

#### Recommendation generation gateway

Session-authenticated endpoints that let the Angular app start and follow a **real** generation in Recommendation Service. User Service stays a gateway: it derives the user from the session, forwards with the private `RECOMMENDATION_API_TOKEN` (never sent to the browser) and does not run any recommendation logic. Both inherit the `/profile` guard: signed-in session cookie, and for `POST` also `X-G15-Request: 1`, a JSON body and no cross-site request (otherwise `403`; no session `401`). Responses are `Cache-Control: no-store`.

`POST /profile/recommendation-generations` takes only `{ "filters": { "genres": [], "languages": [], "actors": [], "directors": [], "year_from": null, "year_to": null, "duration": "any", "count": 10 } }` (same contract as `GET /profile/recommendation-filters`; `count` 5, 10, 15 or 20, default 10). It forwards `{ user_id: <session user>, filters }` to Recommendation Service `POST /recommendations/generate`; a `user_id` or `source` sent by the browser is rejected (`400`), so only `user_requested` generation can be requested.

| Status | Body | Meaning |
|---|---|---|
| `202` | `{ "job_id": "...", "status": "queued" }` | Job queued; returns immediately, inference runs in the background |
| `400` | `{ "error": "..." }` | Invalid body or filters (message from the validator) |
| `409` | `{ "error": "...", "job_id": "...", "status": "queued\|running" }` | A generation is already active for this user; poll that job instead |
| `503` | `{ "error": "..." }` + `Retry-After: <seconds>` when the queue is full | Queue full, or the service/database is unavailable |

`GET /profile/recommendation-generations/JOB_UUID` forwards to `GET /recommendations/generations/JOB_UUID?user_id=<session user>`; a `user_id` query parameter from the browser is ignored, and a job that belongs to another user is indistinguishable from an unknown one (`404 { "error": "Generation job not found." }`; invalid UUID `400`). Success `200`: `{ "job_id", "status": "queued\|running\|succeeded\|failed", "source", "requested_count", "created_at", "started_at", "finished_at" }` plus, when `succeeded`, `recommendation_count`, `outcome` (`llm`, `llm_after_retry`, `fallback_inference_error`, `fallback_validation_error`, `no_candidates`), `attempts`, `used_fallback`, `fallback_reason`, `duration_seconds`; when `failed`, an `error` category (`user_service_unavailable`, `user_not_found`, `movie_catalog_unavailable`, `invalid_request`, `database_error`, `internal_error`, `interrupted`). A deterministic fallback and `no_candidates` are `succeeded`. After any terminal state read the results with `GET /profile/recommendations` (an interrupted job may still have saved a new set).

Gateway rules (`generation_call` in `services/recommendations.py`): `400`, `404`, `409` and `503` keep their status and a safe message (`409` also its `job_id` and `status`, `503` its numeric `Retry-After`); every other upstream error, an invalid body or a transport failure becomes a generic retryable `503`. The older `POST /profile/recommendation-requests` is unchanged (it only validates filters and creates no job); the Angular app no longer calls it. Required environment: `RECOMMENDATION_SERVICE_URL` and `RECOMMENDATION_API_TOKEN` (the same token Recommendation Service uses). Frontend flow and testing: [Recommendation Service README](../recommendation-service/README.md#frontend-integration-angular--user-service--recommendation-service).

Internal `GET /internal/recommendation-users` and `GET /internal/recommendation-context/UUID` require the separate private `AGENT_CONTEXT_TOKEN`. Recommendation Service exposes them to agent clients through `/context/users` and `/context/users/UUID`; User Service remains the storage owner. They return user IDs and paginated watched/watchlist entries with recency timestamps. Full contract and examples: [Recommendation Service README](../recommendation-service/README.md#agent-integration-contract).

API layout: `api/` contains route handlers and registers blueprint hooks. `helpers/` contains authorization/session guards, request parsing helpers and response/cookie helpers. `services/` owns business logic, persistence and service adapters. Helper modules never import API modules.

## Search and profile visibility

Migration `008_profile_visibility.sql` adds `user_profiles.is_public`, default true. It makes existing profiles public once; reruns preserve later privacy choices. Registration and sample ingestion inherit the same public default.

- `GET /profile` and avatar/visibility update responses include `is_public`.
- `POST /profile/visibility` accepts exactly `{"is_public": false}` or true. Session and same-origin mutation header required; updates only the owner.
- `GET /users?q=TEXT&offset=0&limit=25&seed=UUID` searches public usernames/display names by literal, case-insensitive substring. Limit 1–1000, offset 0–1000000, query at most 200 characters. Empty query browses public users. Optional UUID seed gives stable random order for empty queries; otherwise username/UUID order. Returns `users`, `total`, `offset`, `limit`.
- `GET /users/UUID?section=watchlist|watched|recommendations&offset=0` returns public identity (`id`, `username`, `display_name`, `avatar_id`, `bio`), `watched_total`, `watch_minutes` (all watched movies, null if durations are unavailable), and `collection` (`items`, `total`, `offset`, `limit`, fixed 25). Default section is watched; its legacy `watched` field remains. Watchlist items have movie ID/added date; watched items have movie ID/watched date. Recommendations return ID, movie ID, reason, and source through Recommendation Service. Private and missing profiles both return 404. Local visibility/collection reads share a database snapshot; recommendations recheck visibility after the service call.

Discovery requires a signed-in session and disables HTTP caching. It never exposes emails, credentials, or sessions. Public profiles expose all three collections; private profiles expose none of them to other users. Owner profile/history access remains available when private. Movie details come from Movie Service.

### Search inside profile collections

- `GET /profile/watchlist/search?q=TEXT&offset=0` searches the owner's full watchlist and returns matching movie IDs, total, offset, and limit 25.
- `GET /profile/recommendations` accepts optional `q` alongside its existing source/offset parameters. Matching uses the full saved recommendation collection before pagination, retaining the selected source.
- `GET /users/UUID` accepts `q` for every section (watchlist, watched, recommendations). Public visibility is rechecked after remote movie lookups.

All collection searches use literal, case-insensitive movie title/original-title matching, with a 200-character query limit. Metadata stays in Movie Service; recommendation storage stays in Recommendation Service. Missing service data returns a retryable error rather than an incomplete search result.
