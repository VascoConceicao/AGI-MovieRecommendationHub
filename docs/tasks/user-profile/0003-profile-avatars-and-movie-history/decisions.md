# Decisions

## Confirmed Scope

- User authorized implementation in this conversation after task creation; current-conversation execution chosen, no subagent. Actual session model/effort not exposed.
- Profile page uses the existing application palette.
- Provide ten bundled default avatars under frontend `assets/avatars/`; users can switch and persist their choice.
- Store watched history in a new User DB table. Store real movies and filter-ready metadata in Movie DB.
- Place movie ingestion under Movie Service `db/ingestion/`. Add VS Code task `ingest: movies`, following `ingest: users` process task, count prompt, and service/DB startup pattern.
- User enters X movies per run. Treat X as additional new movies, not a total catalog target. Preserve existing catalog rows; skip known source IDs and continue searching for new movies. Report actual added/skipped/failed counts and source exhaustion instead of promising unavailable movies.
- Later, an agent suggesting an unknown movie supplies all required movie information to Movie Service. The service finds existing records locally or validates and stores the supplied data; it never fetches missing information externally. Build the Movie Service create-or-resolve foundation now; defer agent wiring. Reuse known movies and enforce source identity uniqueness even for concurrent requests.
- No external calls from the running app, including backend provider lookups and browser poster requests. Only ingestion may contact external sources. Internal service communication stays allowed; agent-side information sourcing is outside this task. Reject incomplete required metadata rather than enriching it remotely.
- Store and serve posters/images within the application deployment. Ingestion may download permitted images; for later agent-created movies, define an agent-supplied asset contract or use a local placeholder when an image is optional. Never fetch an agent-supplied external URL at runtime.
- Add `POST /admin/reset-movie-db` (proxy `/api/movie/admin/reset-movie-db`) following existing User Service reset behavior: opt-in, bearer token, strict allowlisted `table`/`all` payload, transactional deletion, preserved schema, and affected-table/deleted-row counts.
- Store reset configuration in Movie Service's own ignored `.env`, using the same enabled/token pattern as User Service. Keep credentials service-local and independently configurable; do not read User Service `.env` or reuse user sessions for reset authorization. Document placeholders in `.env.example`, never real tokens.
- Clear endpoints also clear affected user watched state. Clearing the movie catalog clears watched records through an authenticated User Service API; deleting selected movies clears their watched references. User DB reset of all/users includes watched records, and the watched table can be cleared directly. Unrelated table-only resets preserve unrelated history.
- Each service deletes only from its own DB. Coordinate movie/history cleanup through APIs with independently configured service credentials. Report success only after both cleanups finish; define retryable, idempotent handling for partial failure. Do not claim a shared database transaction.
- Keep stable movie identity so clear/reingestion never attaches old history to a different movie.
- Preserve database ownership. Watched records reference Movie Service IDs without cross-database foreign keys.
- Defer marking movies watched and filter UI. Do not invent watched history for real users; isolated development fixtures may verify populated history.
- Use new `user-profile` semantic leaf; no existing tasks moved.

## Pending

- Live TMDB verification awaits user-supplied `TMDB_READ_TOKEN`. Actual catalog count remains user input.
- Deployment must mount/back up the chosen poster directory; infrastructure rollout is outside this phase.
- Explicit metadata refresh and future filter UI remain later work; ordinary ingestion is additive.
- Mark-watched API remains deferred. Future writer must verify Movie Service existence before inserting; no runtime enrichment.
- Public profile/history visibility remains future scope.


## Implementation Decisions

- User authorized random sample watched history in user ingestion. Added `--max-watched` and VS Code input (default 10), targets 0..min(max, catalog size), including admin/existing generated users. Fetch IDs via Movie Service pagination, preserve existing history, avoid duplicate growth on reruns, and leave watched dates unknown. Zero disables seeding; empty catalog adds no history.

- Added all-history watch time beside movie count. User Service aggregates runtimes through Movie Service API in batches, preserving DB isolation; live events update the total. Display days plus remaining minutes, omit zero days, and show an em dash for missing/unavailable runtimes. Each watched movie counts once.

- Replaced timed history polling with authenticated SSE backed by PostgreSQL LISTEN/NOTIFY triggers. Direct committed writes notify the affected user; reconnect resyncs, in-flight events queue a follow-up reload, and navigation closes the stream. Nginx buffering disabled; production reserves request threads with a bounded stream count.

- Removed empty-history explanation and manual Refresh button. History refreshes quietly every 10 seconds while visible and on window/tab return; requests do not overlap and polling stops on navigation. Empty out-of-range pages return to page one.

- Removed the avatar-save confirmation and its reserved space; successful selection updates the avatar and closes the modal.

- Removed avatar-picker subtitle. User preference: short, functional UI text; avoid decorative taglines and unnecessary explanations.

- Moved avatar modal near the viewport top (24–80px responsive offset), keeping horizontal centering and internal scrolling on small screens.

- Avatar picker now uses a native modal dialog: backdrop, close button/Escape, keyboard focus containment/return, and close after successful save. Save errors remain visible inside the modal.

- Removed profile/history taglines and email from the page. Avatar now opens its picker directly, with a pencil on hover/focus and a visible edit badge on touch devices.

- User requested removal of the profile movie-data credits footer; removed its markup, styles, and unused logo asset.

- TMDB popular/details/credits for ingestion; default prompt 100 additional movies. Offline JSON import supports the same required payload without network. Ingestion commits per movie, skips existing identities, and reports partial/exhausted runs.
- Required fields: canonical source/source ID, title/original title, synopsis, release date, runtime, type, genres, cast, directors, languages, countries. Genres/cast use GIN indexes; date/runtime use scalar indexes. Images optional. No fabricated metadata or external runtime enrichment.
- Store JPEG posters under persistent `movie-service/assets/posters/` or absolute `MOVIE_MEDIA_DIR`; SHA-256 filename, width 500 at ingestion, atomic file write, local fallback. Agent payload may reference an existing key or omit it. Retain files during catalog reset; offline garbage collection remains optional maintenance.
- Movie UUIDs are random and never reused. `(source, source_id)` uniquely identifies a catalog entry. Concurrent writes serialize with reset and never duplicate identity.
- `/profile` and `/account` are private session-backed routes. Ten original palette-based SVG avatars; default ID 1, selectable 1–10. Watched table unique per user/movie, nullable watched date, newest recorded first, 25 per page.
- Reset supports `all`/`movies` (full catalog). No per-movie delete route added. Movie deletion + pending job commits first; new movie writes pause until authenticated User Service cleanup succeeds. Retrying resumes the pending job.
- User cleanup uses a dedicated shared service credential, separate from both admin reset tokens. It retires movie UUIDs, clears watched rows, and saves an idempotency receipt. A trigger serializes watched writes against cleanup and rejects retired IDs. Coordination records survive resets. User reset all/users/watched_movies clears watched state; session/profile-only reset keeps unrelated history.
- Added generated local write/reset/cleanup credentials to ignored service `.env` files without printing secrets. TMDB token remains unconfigured. Default tracked examples keep reset disabled.
- Ran additive schema migrations on local development databases. Destructive reset checks used separate temporary databases only; existing user data preserved.

## Model Recommendation Basis

- Native Codex catalog supports `gpt-6.1-sol` and `medium`; use this reliable default for the cross-service implementation.
- Reviewed [Codex model guidance](https://learn.chatgpt.com/docs/models) and [Claude model configuration](https://code.claude.com/docs/en/model-config) during creation.
- Claude `sonnet` is a documented alias; access/version here is Unverified and effort advisory.
- Reassessed after ingestion/reset scope clarification: retain the same model/effort recommendations for this scoped cross-service implementation.
- No measured comparison establishes total-token efficiency for this task. Reassess recommendations if scope changes.

- Added `ingest: all`: movies first, then users, using existing ingestion scripts and count/max-watched inputs. Wrapper: `app/backend/common/scripts/ingestion/ingest-all.sh`. Development/testing stay in root `scripts/`, per user correction. Stops on failure; no duplicated ingestion logic. Delegation, arguments, invalid inputs, and failure propagation checked with isolated stub scripts. Live ingestion not run (TMDB credential absent).

- Profile stats now share value size, spacing, and stretched alignment. Missing, invalid, or negative watch minutes display as 0 minutes.

- Simplified profile stats into equal-width subtle tiles, matching numeric typography and unit labels below. Watch duration shows separate days/minutes values, hiding zero days. Responsive tiles stay side by side below identity when space is limited.

- Added VS Code `clear: all` and shared backend reset runner. Preflights isolated service .env tokens/settings, calls Movie then User reset endpoints, clears watched history, and stops on failure. Recommendation currently has no application tables. Mock checks passed for order, credentials, payload, preflight and failure handling; no real reset executed.

- Organized Commander ingestion/clear tasks into Backend/Databases/Ingestion and Clear subgroups. Added individual Movie/User/Recommendation clear tasks using the shared runner selector. Recommendation reports no tables; Movie starts User for coordinated history cleanup. Mock selection and task/group reference checks passed; no actual reset run.

- Moved default poster storage to Movie Service assets/posters, including existing local images. Ingestion/runtime share the updated default; filenames and database keys remain unchanged. Custom MOVIE_MEDIA_DIR overrides remain supported.

- Ingest/clear tasks now depend on hidden ensure-service tasks. Manager ensure mode keeps existing processes, starts absent services with tracked PID/log, and waits for health under the component lock. DB ensure uses --no-recreate; explicit run behavior still restarts. Existing local Movie/User services reused; isolated start/reuse checks confirmed stable PID.

- Added simple public Credits page with TMDB required notice and official locally stored logo. Profile and auth pages link to it; no runtime external asset requests.

- User changed metadata requirements: only source/source_id/title required; other movie metadata nullable. Added additive migration, normalization of unknown provider runtime and missing fields, null-safe serialization/UI, and updated MovieInput schema. Watch time sums known runtimes.

- Required metadata now includes synopsis, genres, actors and directors alongside identity/title. Enforced new DB writes while preserving legacy rows. Ingestion interleaves genre feeds, deduplicates candidates, skips failed movies, and continues until requested NEW successful inserts or explicit source exhaustion. Added progress and validation reasons. User confirmed genre spread, not fewer genres per movie.

- Duration now required: integer 1–10000 minutes for ingestion/API/new DB writes. Missing/zero provider runtimes skipped. Additive constraint preserves 7 existing movies with unknown runtime; no fabricated durations or deletion.

- Movie cards now open a responsive native detail dialog using already-loaded local catalog data. Shows poster, synopsis, cast, directors and available metadata; hides missing optional fields. Keyboard opening, focus containment/return, Escape, backdrop/close button and mobile width verified in Chromium. Frontend build and 29 existing tests passed.

- Added debounced title search beside watched-history heading, across full history via Movie Service API batches. Results paginate independently; profile count/watch-time remain unchanged. Missing Movie Service gives an explicit search error.

- Centered movie details dialog independently of avatar picker. Added Mark as not watched action and authenticated, same-origin POST /profile/watched/remove scoped to current user. Successful deletion closes dialog and refreshes history/stats; SQL notification updates other sessions. Ownership/idempotency verified in rolled-back transaction.

- Refactored account screen into HomePage shell with routed tabs. Profile moved to components/tabs/profile; reusable tab navigation in components/common/tab-navigation. /home defaults to profile; old account/profile URLs redirect. Login/register land on main. Existing logout tests moved with HomePage.

- Added profile subtabs (final order My list, Watched, Recommendations), local catalog browsing and user-owned watchlists. Recommendations remains empty by request. Added max-watchlist ingestion prompt; excludes watched movies and preserves rerun behavior. Mark as watched on aligned cards atomically removes watchlist membership; API/database prevent overlap. Shared MovieCollection handles catalog/watchlist views and modal actions. Updated reset cleanup and API docs. Isolated DB/API checks passed for ownership, CSRF, idempotency, transition, ingestion reruns, and cleanup; browser checks passed for tabs, aligned buttons, add/remove transition, reload and mobile.

- Added Recommendation DB schema and service-token endpoints: paginated per-user list, upsert by user/movie, idempotent delete, and isolated admin reset. Local/Docker startup migrations; generated ignored API/reset credentials. Clear tasks include actual Recommendation reset first. No ingestion, agent generation, or frontend integration. Future caller supplies resolved user/movie IDs; lifecycle integration remains future work. Isolated DB/API checks and 7 existing tests passed.

- Movie reset now removes stored poster JPEGs, including orphan files, from configured poster storage before completing. Pending cleanup retries on filesystem errors; ingestion/reset share a lock. Existing assets retained until the user next runs clear. Verified 7 existing Movie tests and temporary endpoint/filesystem checks; no live reset executed.

- Added Get recommendations button and centered filter modal in a dedicated profile child component. User confirmed genres, release years, duration, languages, count, actors and directors. Catalog supplies valid choice values; up to 10 selections each, nullable year bounds, duration presets, count 5/10/15/20. User session gateway rejects supplied user IDs, enforces same-origin mutations, and keeps service tokens server-side. Recommendation Service stores normalized versioned filter requests with awaiting_generation status and offers user-scoped reads. Clear endpoint now clears requests too. No ingestion, prompt generation or LLM calls; modal states generation is not connected. Local services reloaded with additive migration, credentials configured privately, docs updated.
- Validation: 7 Movie + 7 Recommendation + 47 User + 29 frontend existing tests passed (90 total); frontend build passed. Temporary isolated PostgreSQL/API checks passed for migrations, validation, persistence, ownership, auth and reset; temporary DB removed. Gateway checks covered session/CSRF and user spoofing. Chromium covered selections, range validation, save payload, failure/retry, Escape/focus return and mobile fit; fixed cancel handler to allow Escape normally. Live authenticated filters returned catalog choices through all three services. No real filter requests seeded and no production data cleared.

- Replaced native recommendation dropdowns with shared components/common/filter-select (palette colors, search, keyboard arrows/Enter/Escape, direct selection, removable chips). Languages show full English display names while API stores original codes. Actors/directors are free-text names, Enter adds a chip and submit includes unfinished name input; API trims/deduplicates and accepts names outside catalog, capped at 10 names of 200 characters each. Catalog filter options now only return genres/languages, avoiding the full actor list. Duration/count reuse the shared selector. Future flow clarified: request endpoint directly triggers agent/inference when connected; persistence does not imply agent DB polling. Prompt generation/inference still absent.
- Validated 29 frontend + 7 Recommendation + 7 Movie tests, production build, free-name validation, and Chromium desktop/mobile checks (auto-add, full language names with canonical payload, typed names, submit, keyboard, Escape). Reloaded Movie/Recommendation services; no live requests generated or content cleared.

- User clarified scope: data endpoints only; teammate owns agent wiring, prompts, inference, recency weighting and scheduling. Removed outgoing agent adapter/config. POST recommendation-requests validates and returns normalized user_id/source/filters with generation_available=false; it performs no request persistence or agent dispatch. Removed request-read endpoints and new-install request migration; legacy request table stays unused until normal clear. Result DB remains, now with required auto/user_requested source and unique user/movie/source so both origins can coexist. Source filtering added to private listing and frontend; cards show source/reason and movie details, with pagination.
- Added private User Service agent-context token and read-only user-ID pagination plus per-user watched/watchlist pages with watched_at (nullable), recorded_at, added_at and as_of. Preserves raw recency evidence; no fabricated watch dates or weighting. Browser cannot choose another user in the session gateway. Documented teammate contract and examples in Recommendation README/OpenAPI. Applied additive source migration and reloaded services; no live content cleared.
- Validation: final data-only API checks confirmed no DB writes on filter submission, source separation/ownership and canonical payload. Isolated User DB checks covered timestamps/nulls, context/user pagination, tokens and session scoping. Browser checks covered All/Auto generated/User requested results, detail modal and filter preparation. Live proxy checks passed. Latest existing suites passed (Recommendation 87, User 47, frontend 29); frontend build passed. Temporary test databases removed. Parallel test-file additions were left intact.

- Simplified empty states: No recommendations yet / No movies in your list yet / No watched movies yet. Removed recommendation-list error banner when no results, per user request; all source filters use the empty message, including failed empty loads. Renamed recommendation trigger/modal/submit to Generate recommendations. Live API returned HTTP 200 empty lists for all sources; frontend build and browser empty-state/fallback checks passed.

- User confirmed moving agent-facing context endpoints into Recommendation Service. Added api/context.py routes GET /context/users and /context/users/{user_id}, protected by Recommendation API token. services/context.py reads existing User Service internal endpoints with private shared context token; DB ownership stays unchanged. Added Context API Swagger group, full response schemas and synthetic pagination/null-date examples in Swagger and Recommendation README. Configured local internal token privately and reloaded service. 87 existing tests, live proxy/auth/validation checks, Swagger browser rendering, and strict OpenAPI/Flask coverage validation for Recommendation/User passed. Corrected stale delete-route parameter name found by doc validation.

- Swept all backend services (Movie, Recommendation, User): moved non-route API functions into service-local helpers, including token guards, session/mutation guards, credential parsing, signed-in cookie responses, filter-option assembly, no-store hooks and error handlers. Extracted inline User reset/cleanup authorization too. API files register imported hooks and define only routes; common no-store implementation per service avoids copies. Profile imports cookie constants from helpers instead of another API. Dockerfiles copy helpers; helper placeholders removed and README layout documented. Behavior preserved: 93 Movie + 87 Recommendation + 184 User tests passed (364). AST sweep verified only route handlers remain defined in API files; services reloaded and live health/auth/cache-header checks passed.

- Moved filter submission into Recommendation Context API: POST /context/recommendation-requests, implemented in api/context.py and tagged Context API in Swagger. Updated authenticated User Service forwarding; browser-facing profile path stays stable. Updated existing tests and README. 87 Recommendation + 184 User tests, OpenAPI route validation and live filter-submission/Swagger checks passed. Services reloaded; no data saved.

- Ran project:swagger across all three services. Refreshed OpenAPI schemas, request bounds/headers, response bodies/examples/status codes, source-filter results, actual catalog choices, no-persistence filter response, SSE and reset behavior. Preserved Context API examples/group and documented internal endpoints separately. Removed invalid empty required array; made movie lookup/browse response variants unambiguous. Refreshed service viewers without copying specs into the parent. Strict validation matches all 41 Flask operations (10 Movie, 10 Recommendation, 21 User). All three Swagger viewers rendered expected operation counts through proxy; parent viewer served. No API behavior changes or mutation calls.
