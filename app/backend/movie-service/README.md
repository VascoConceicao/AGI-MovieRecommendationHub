# Movie Service

Flask 3.1 on Python 3.12. `main:create_app` creates the application; the only endpoint is `GET /health`.

This component's `db/compose.yaml` owns its database and volume. Run `sh scripts/database/run-db.sh` from this directory to start its database using this service's `.env`. The root Compose file includes this same definition for combined startup.

This service owns one dedicated database running PostgreSQL 18. From the repository root, `scripts/development/run-backend.sh movie` loads the local database configuration and serves on `http://127.0.0.1:4206`. Docker is used only for the database.

The health endpoint runs `db/sql/health.sql` against this service's database. It returns HTTP 200 with `status: ok` and `database: up` only after `SELECT 1` succeeds; missing configuration or connection/query failure returns HTTP 503 with `status: unavailable` and `database: down`. Both responses identify `movie-service` and disable caching. Connection timeout is 3 seconds; statement timeout is 2 seconds. This is database readiness, not a liveness probe.

This service owns `requirements.txt`, its fully resolved `requirements.lock`, and `.venv`. Install it as documented in the root README. The shared package only supplies utilities; connections and SQL remain service-owned.

`api/` handles HTTP; `services/` contains logic and adapters; `helpers/` owns HTTP guards, validation helpers and response helpers; `models/` is reserved. `db/migrations/` holds catalog and reset schemas; `db/seeds/` is reserved. Product APIs are listed below.

## API docs

Swagger UI: `/static/swagger.html`. OpenAPI file: `static/swagger.json`.
Through the local proxy: `http://127.0.0.1:4205/api/movie/static/swagger.html`.
The UI uses pinned Swagger UI CDN assets; internet is needed for the viewer.
Update selected services/endpoints with the `project` plugin’s `swagger` skill; `all` updates every service.

## Movie catalog and ingestion

Run `flask --app main:create_app init-db` to apply idempotent migrations. Local and container startup do this automatically. `movies` stores filter-ready scalar fields plus arrays for genres, cast, directors, languages, and countries. Indexed genres/cast, duration, and release date support later filtering. `(source, source_id)` is unique; random movie UUIDs prevent history from attaching to a different movie after reset. Agent writes must use canonical source identities.

See [ingestion setup and movie payload](db/ingestion/README.md). VS Code task `ingest: movies` adds the requested number of new movies. TMDB access and poster downloads happen only in ingestion. Runtime uses local data and internal service calls.

| Method | Path | Behavior |
| --- | --- | --- |
| GET | `/movies?ids=UUID,UUID` | Read 1–50 movies by UUID. Missing IDs omitted. |
| POST | `/movies` | Validate agent-supplied metadata; create or reuse movie. Requires `MOVIE_WRITE_TOKEN`. |
| GET | `/posters/KEY.jpg` | Serve an existing local content-addressed JPEG. |
| POST | `/admin/reset-movie-db` | Clear catalog, watched/watchlist entries, and stored posters; requires enabled reset and `MOVIE_RESET_TOKEN`. |

Proxy prefix: `/api/movie`. Put runtime tokens in this service's ignored `.env`. `.env.example` documents names, never live values. A missing write token disables movie creation through the API; ingestion writes through the owning service's persistence module.

## Reset with watched-history cleanup

Set `MOVIE_RESET_ENABLED=true` and a private `MOVIE_RESET_TOKEN`. Send JSON `{"table":"all"}` or `{"table":"movies"}` with `Authorization: Bearer YOUR_MOVIE_RESET_TOKEN`. Both selections clear the entire movie catalog. No individual movie deletion endpoint is introduced.

Movie reset also clears watched state through User Service `/internal/clear-watched`. Set `USER_SERVICE_URL` to the internal User Service address and configure a dedicated `WATCHED_CLEANUP_TOKEN` on both services. This shared **cleanup credential** is separate from each service's independent admin reset token. No service reads another service's `.env` or database.

Movie deletion and a pending `catalog_resets` operation commit together. New movie creation is blocked while cleanup is pending. User Service handles each operation once, records a receipt, clears watched rows, and retires deleted movie UUIDs. The reset reports 200 only after cleanup succeeds. A failure returns 503 with `cleanup_pending: true`; repeat the same reset to resume it. User cleanup is idempotent even if its response was lost. Each database has its own transaction; there is no cross-database transaction.

Successful response includes `cleared_tables`, `deleted_rows`, `watched_deleted_rows`, and `operation_id`. Operation/retired-ID tables are coordination records, deliberately retained during content reset. Stored poster JPEGs (including orphaned posters) are deleted from `MOVIE_MEDIA_DIR`, default `assets/posters/`. The directory and unrelated files stay intact. Poster deletion must finish before the reset completes; filesystem failures leave the operation pending for retry. Reset and ingestion cannot run together. Schema stays intact. Invalid selections return 400; invalid token 401; disabled reset 404.

Future watched-write API must verify movie existence through Movie Service before saving. The User DB trigger also serializes writes against cleanup and rejects retired UUIDs. Marking watched remains deferred.

`POST /movies/duration` accepts `{"ids":["UUID"]}` (1–1000 IDs), returning `total_minutes` and `missing_count`. Duplicate IDs count once. This read-only aggregation supports all-history watch time through the service API.

`GET /movies/ids?after=UUID` returns up to 1000 sorted catalog UUIDs and `next_cursor` (null when complete). User ingestion uses this API to seed sample watched history while keeping DB ownership separate.

Source, source ID, title, synopsis, genres, actors, directors, and positive duration_minutes are required. Missing optional metadata is stored as SQL NULL, including blank optional text and empty lists. Missing or zero TMDB runtime is rejected; ingestion continues to the next candidate. Supplied invalid values are still rejected. Watch time sums known runtimes; unknown runtimes add no minutes.

Ingestion rotates across TMDB genre-specific discovery feeds and deduplicates movies across genres. It keeps full genre metadata and continues after invalid/duplicate records until COUNT new movies are saved. Genre coverage is varied, not an exact quota (movies can have several genres). Source exhaustion returns failure with actual counts; it never reports a partial run as complete.

`GET /movies/filter-options` returns sorted distinct genres and languages from the local catalog for recommendation filters. Empty catalog returns empty arrays.

API layout: `api/` contains route handlers and registers blueprint hooks. `helpers/` contains authorization/session guards, request parsing helpers and response/cookie helpers. `services/` owns business logic, persistence and service adapters. Helper modules never import API modules.

## Movie search batches

`GET /movies?q=TEXT&offset=0&limit=25&seed=UUID` browses the local catalog without external calls. Literal, case-insensitive substring matching covers title and original title. Query max 200 characters; offset 0–1000000; limit 1–1000. Responses contain `movies`, `total`, `offset`, and `limit`.

An optional UUID seed gives deterministic random ordering for an empty query, with UUID tie-break. Reuse the seed across offsets to page through unchanged catalog data without repeats. Nonempty searches keep title/UUID order. The existing IDs lookup and POST browse API remain available.
