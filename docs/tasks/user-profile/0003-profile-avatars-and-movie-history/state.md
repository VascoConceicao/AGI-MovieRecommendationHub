# Task: Profile page, avatars, watched history, and movie catalog

## Assigned To

Unassigned

## Status

Completed. Accepted by user on 2026-10-09.

## Goal

Build a profile page with ten selectable default avatars and persisted watched history. Add a real-movie catalog and repeatable ingestion, with metadata ready for future filters.

## Context

Use the existing palette in `app/frontend/src/app/assets/palette.json`. Put default avatars under `app/frontend/src/app/assets/avatars/`.

User Service owns avatar choice and watched records in User DB. Movie Service owns real movies in Movie DB. Services access only their own databases; movie details cross service APIs, with no cross-database foreign keys.

The running app has no external-service dependencies or outbound provider calls, including browser image requests. Only ingestion may access external sources. Agent-created movies receive their required data from the agent; internal service APIs remain allowed.

Expanded scope includes watched/watchlist actions, recommendation filters and result storage, and agent context endpoints. Prompt generation, LLM calls, and background scheduling remain with the agent owner.

## Todo

- [x] Inspect current account page, profile schema, assets, service contracts, and database conventions.
- [x] Choose a real-movie source and image storage/delivery strategy; use app-owned image storage/delivery, and document ingestion-only credentials, attribution, and reproducibility.
- [x] Add Movie DB schema for stable IDs, titles, synopsis, genres/type, cast, directors, duration, release date/year, language, country, and image references; assess useful extra fields.
- [x] Add repeatable ingestion under `app/backend/movie-service/db/ingestion/`, with deduplication and invalid/missing data handling. Add VS Code task `ingest: movies` with a user-entered count of additional movies per run; preserve existing records and skip duplicates while finding new movies.
- [x] Provide a Movie Service create-or-resolve contract for later agent suggestions: reuse existing movies, otherwise validate and store all required real-movie metadata supplied by the agent. No external lookup or enrichment at runtime. Agent integration comes later.
- [x] Add Movie Service table-clear endpoint following User Service reset conventions, with isolated configuration/token in Movie Service `.env`; coordinate watched-state cleanup through User Service API, update clear examples/docs and User Service reset handling for the new watched table. Handle retries/partial failures without cross-service DB access.
- [x] Add a new watched-movies table in User DB, referencing Movie Service IDs; define history order, duplicate policy, and date semantics.
- [x] Add ten default avatars, a default for new/existing users, and persistent selection with authorization and allowed-ID validation.
- [x] Build profile page and watched movie cards using the palette, with responsive layout, accessible selection, loading, empty, and failure states.
- [x] Validate ingestion reruns, persistence, authorization, service isolation, and profile behavior; run relevant existing checks.
- [x] Update service/setup docs and task records with implementation and validation results.

## Plan

1. Define data contracts, source, image strategy, and schema.
2. Implement movie catalog/ingestion and user-owned avatar/history storage.
3. Build profile UI and validate the complete flow.

## Changes Made

- User authorized random sample watched history in user ingestion. Added `--max-watched` and VS Code input (default 10), targets 0..min(max, catalog size), including admin/existing generated users. Fetch IDs via Movie Service pagination, preserve existing history, avoid duplicate growth on reruns, and leave watched dates unknown. Zero disables seeding; empty catalog adds no history.

- Added all-history watch time beside movie count. User Service aggregates runtimes through Movie Service API in batches, preserving DB isolation; live events update the total. Display days plus remaining minutes, omit zero days, and show an em dash for missing/unavailable runtimes. Each watched movie counts once.

- Replaced timed history polling with authenticated SSE backed by PostgreSQL LISTEN/NOTIFY triggers. Direct committed writes notify the affected user; reconnect resyncs, in-flight events queue a follow-up reload, and navigation closes the stream. Nginx buffering disabled; production reserves request threads with a bounded stream count.

- Removed empty-history explanation and manual Refresh button. History refreshes quietly every 10 seconds while visible and on window/tab return; requests do not overlap and polling stops on navigation. Empty out-of-range pages return to page one.

- Removed the avatar-save confirmation and its reserved space; successful selection updates the avatar and closes the modal.

- Removed avatar-picker subtitle. User preference: short, functional UI text; avoid decorative taglines and unnecessary explanations.

- Moved avatar modal near the viewport top (24–80px responsive offset), keeping horizontal centering and internal scrolling on small screens.

- Avatar picker now uses a native modal dialog: backdrop, close button/Escape, keyboard focus containment/return, and close after successful save. Save errors remain visible inside the modal.

- Removed profile/history taglines and email from the page. Avatar now opens its picker directly, with a pencil on hover/focus and a visible edit badge on touch devices.

- Removed profile movie-data credits footer and unused styles/logo at user request.

- Created task and initial implementation phase on 2026-10-09.
- Created exact branch `user-profile/0003-profile-avatars-and-movie-history` from clean `development`.
- Registered task as Current in `docs/TODO.md`.
- Added user-requested per-run ingestion count, VS Code task, additive catalog growth, future agent movie creation contract, and service-local reset endpoint/token.
- Clarified agent supplies movie information; runtime validates/stores only, with external access limited to ingestion and locally served images.
- Clarified clear endpoints also remove affected watched state, with API-based cleanup across services and explicit partial-failure handling.
- Implemented Movie/User APIs and migrations, count-driven ingestion/VS Code task, durable reset cleanup, palette-based profile UI, ten SVG avatars, local poster delivery, and service/setup/API docs.
- Fixed frontend launcher after user reported the npm/nvm error; kept `~/.npmrc` global prefix intact.
- Execution stayed in this conversation; no subagents, commits, staging, or branch changes.

## Validation

- User-ingestion follow-up: 47 User + 7 Movie tests passed. Isolated integration checked empty catalog, 1,005-ID pagination, per-user random cap, existing-user backfill, stable reruns, max=0, invalid input and unavailable source. Temporary databases/server and credential report removed.

- Watch-time follow-up: production build, 47 User + 7 Movie tests, isolated DB/API checks, and browser formatting/live-update/mobile checks passed. Verified 31 movies across two pages total 14,415 minutes; empty history is zero, duplicate IDs count once, and missing/unavailable durations remain unknown. Temporary test databases/server removed.

- Live-update follow-up: 47 User Service tests and 29 frontend tests passed; production build passed. Isolated DB checks verified insert/update/delete/truncate events, rollback silence, user isolation, session revocation, stream capacity, and connection cleanup. Real browser through Nginx saw direct DB insert in 636ms, delete refresh, reconnect recovery, and no timed history reads. Restarted local User Service/proxy; removed temporary test DB and servers.

- Automatic-history follow-up: build and browser checks passed for new movie appearance without clicks, window-focus refresh, removed copy/button, and polling cleanup after navigation.

- Modal follow-up: production build and browser checks passed for keyboard focus wrapping/return, Escape, close/backdrop dismissal, save success/error, and mobile fit.

- Creation preflight passed; global task ID allocated as 0003.
- Task and TODO validators passed; task registered as Current.
- Template unchanged against HEAD; whitespace check passed.
- Movie Service: 7 existing tests passed. User Service: 47 existing tests passed. Frontend: 29 existing tests passed.
- Frontend production build passed; API JSON references, avatar SVGs, shell syntax, and diff whitespace passed.
- Isolated PostgreSQL/runtime checks passed: required metadata, concurrent deduplication, private profile access, avatar persistence, history reads, reset authorization/isolation, idempotent cleanup, partial-failure recovery, retired-ID rejection, and concurrent watched insert protection.
- Offline ingestion: three count=1 runs each added one new movie; fourth reported exhaustion without duplicates/deletion.
- Temporary verification databases and servers removed after checks. Existing development data preserved.
- Chromium desktop/mobile checks passed: real API flows, keyboard avatar selection, save/reload, empty/populated history, all images loading, local-only requests, movie-service failure/recovery, no horizontal overflow or JS errors.
- Initial frontend checks used Node 24 directly because of an npm/nvm prefix conflict. Follow-up fixed `with-node.sh`: portable nvm loading under dash, resolve installed Node through `nvm which`, and prepend its bin directory without changing user npm settings. Exact VS Code frontend launch now builds and returns HTTP 200; the normal frontend test launcher also passes all 29 tests. Browser required temporary extracted libraries; no project dependency changes.
- Live TMDB import not run: `TMDB_READ_TOKEN` absent. External provider behavior remains unverified; offline ingestion and runtime are verified.

## Next Steps

- User accepts, requests retry, or stops phase review.
- Set ingestion-only `TMDB_READ_TOKEN` and run VS Code `ingest: movies` with the desired count when ready to load the real catalog.

- Added `ingest: all`: movies first, then users, using existing ingestion scripts and count/max-watched inputs. Wrapper: `app/backend/common/scripts/ingestion/ingest-all.sh`. Development/testing stay in root `scripts/`, per user correction. Stops on failure; no duplicated ingestion logic. Delegation, arguments, invalid inputs, and failure propagation checked with isolated stub scripts. Live ingestion not run (TMDB credential absent).

- Profile stats now share value size, spacing, and stretched alignment. Missing, invalid, or negative watch minutes display as 0 minutes.

- Simplified profile stats into equal-width subtle tiles, matching numeric typography and unit labels below. Watch duration shows separate days/minutes values, hiding zero days. Responsive tiles stay side by side below identity when space is limited.

- Added VS Code `clear: all` and shared backend reset runner. Preflights isolated service .env tokens/settings, calls Movie then User reset endpoints, clears watched history, and stops on failure. Recommendation currently has no application tables. Mock checks passed for order, credentials, payload, preflight and failure handling; no real reset executed.

- Organized Commander ingestion/clear tasks into Backend/Databases/Ingestion and Clear subgroups. Added individual Movie/User/Recommendation clear tasks using the shared runner selector. Recommendation reports no tables; Movie starts User for coordinated history cleanup. Mock selection and task/group reference checks passed; no actual reset run.

- Fixed local clear-task configuration: User reset was disabled with no token. Enabled it and generated a service-local token in ignored .env, restarted User Service, and verified both reset endpoints authenticate and reject invalid table selections without deletion.

- Moved default poster storage to Movie Service assets/posters, including existing local images. Ingestion/runtime share the updated default; filenames and database keys remain unchanged. Custom MOVIE_MEDIA_DIR overrides remain supported.

- Ingest/clear tasks now depend on hidden ensure-service tasks. Manager ensure mode keeps existing processes, starts absent services with tracked PID/log, and waits for health under the component lock. DB ensure uses --no-recreate; explicit run behavior still restarts. Existing local Movie/User services reused; isolated start/reuse checks confirmed stable PID.

- Added simple public Credits page with TMDB required notice and official locally stored logo. Profile and auth pages link to it; no runtime external asset requests.

- Corrected Credits logo: prior CDN image was Netflix, not TMDB. Replaced with official blue_short SVG from TMDB logos-attribution page; visually verified rendered Credits page in Chromium.

- User changed metadata requirements: only source/source_id/title required; other movie metadata nullable. Added additive migration, normalization of unknown provider runtime and missing fields, null-safe serialization/UI, and updated MovieInput schema. Watch time sums known runtimes.

- Required metadata now includes synopsis, genres, actors and directors alongside identity/title. Enforced new DB writes while preserving legacy rows. Ingestion interleaves genre feeds, deduplicates candidates, skips failed movies, and continues until requested NEW successful inserts or explicit source exhaustion. Added progress and validation reasons. User confirmed genre spread, not fewer genres per movie.

- Duration now required: integer 1–10000 minutes for ingestion/API/new DB writes. Missing/zero provider runtimes skipped. Additive constraint preserves 7 existing movies with unknown runtime; no fabricated durations or deletion.

- Simplified watch-time tile to one compact days/minutes value with small unit suffixes and one watch-time label. Zero days remain hidden; accessible label spells out units.

- Removed Credits link from profile header at user request; login/register links and Credits page remain.

- Watch-time units now read day/days and min, retaining the compact layout.

- Movie cards now open a responsive native detail dialog using already-loaded local catalog data. Shows poster, synopsis, cast, directors and available metadata; hides missing optional fields. Keyboard opening, focus containment/return, Escape, backdrop/close button and mobile width verified in Chromium. Frontend build and 29 existing tests passed.

- Added debounced title search beside watched-history heading, across full history via Movie Service API batches. Results paginate independently; profile count/watch-time remain unchanged. Missing Movie Service gives an explicit search error.

- Centered movie details dialog independently of avatar picker. Added Mark as not watched action and authenticated, same-origin POST /profile/watched/remove scoped to current user. Successful deletion closes dialog and refreshes history/stats; SQL notification updates other sessions. Ownership/idempotency verified in rolled-back transaction.

- Moved Mark as not watched directly below the movie poster, including mobile layout; unavailable-movie removal remains available.

- Refactored account screen into HomePage shell with routed tabs. Profile moved to components/tabs/profile; reusable tab navigation in components/common/tab-navigation. /home defaults to profile; old account/profile URLs redirect. Login/register land on main. Existing logout tests moved with HomePage.

- Extracted tab routes to components/tabs/tabs.routes.ts. Navigation labels/links derive from the same definitions used by the router.

- Moved tab route definitions to pages/home/tabs.routes.ts, per user request; updated imports.

- Search refreshes quietly with existing results visible; queued search requests preserve background mode and do not show the history loader.

- Added profile subtabs (final order My list, Watched, Recommendations), local catalog browsing and user-owned watchlists. Recommendations remains empty by request. Added max-watchlist ingestion prompt; excludes watched movies and preserves rerun behavior. Mark as watched on aligned cards atomically removes watchlist membership; API/database prevent overlap. Shared MovieCollection handles catalog/watchlist views and modal actions. Updated reset cleanup and API docs. Isolated DB/API checks passed for ownership, CSRF, idempotency, transition, ingestion reruns, and cleanup; browser checks passed for tabs, aligned buttons, add/remove transition, reload and mobile.

- Removed catalog browsing from My list per user correction. Only personal saved watchlist is rendered/fetched. Watchlist and watched pagination now show current page / total pages. Admin checked: 206 watched, zero watchlist, rather than all catalog movies.

- Unified profile subtab spacing with 24px panel padding, matching section header sizing, and no extra empty-state margins.

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

- Multi-select recommendation dropdowns now stay open after choosing genres/languages, resetting keyboard selection for the remaining options. Close on selection limit, blur or Escape; single-choice selectors still close after selection. Chromium checks for consecutive choices and closing behavior plus production build passed.

- User accepted and requested completion plus commit/push. Final full suite: 567 passed, 0 failed/skipped, 100% lines and branches across scripts, common, Movie, Recommendation, User, and frontend. Latest frontend build and multi-select browser check passed. Agent implementation remains outside this completed task.
