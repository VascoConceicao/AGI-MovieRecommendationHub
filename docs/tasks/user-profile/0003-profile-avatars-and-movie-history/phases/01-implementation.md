# Phase: Implement profile and movie catalog foundation

## Status

Completed.

## Recommended Model

### Codex

- Model: `gpt-6.1-sol`
- Effort: `medium`

### Claude Code

- Model: `sonnet` (Unverified)
- Effort: `medium` (advisory)

## Goal

Deliver a palette-based profile page with persistent avatar selection and watched history backed by a real-movie catalog and repeatable ingestion.

## Scope

1. Inspect existing profiles, authentication, asset serving, DB migrations, and service APIs. Resolve pending source, image, visibility, and data-contract choices.
2. Add Movie DB catalog schema with stable source IDs, titles, synopsis, genres/type, cast, directors, runtime, release date/year, languages, countries, and image references. Assess extras such as certification and provider ratings without assuming availability.
3. Add documented ingestion under `app/backend/movie-service/db/ingestion/` and VS Code task `ingest: movies` with count input and Movie Service/DB startup dependencies, following `ingest: users`. Each run requests X additional movies; preserve existing rows, skip duplicates, and continue until X new movies or report source exhaustion/failures. Handle credentials outside Git, pagination/rate limits, invalid records, partial failures, and missing images. External access is limited to this ingestion process. Download permitted images into persistent app-owned storage and serve them internally; no external poster URLs in the runtime UI.
4. Add a Movie Service create-or-resolve contract for later agent suggestions. Match agent-supplied identity against local records, reuse existing movies, validate/store all required agent-supplied information for unknown movies, and prevent concurrent duplicates. Reject incomplete required data; do not perform external lookups. Define agent-supplied image handling or an optional-image local placeholder; never download external URLs at runtime. Agent integration remains later work.
5. Add Movie Service `POST /admin/reset-movie-db` following User Service's opt-in bearer-token reset pattern, with Movie Service-local `.env` configuration, strict table allowlist, transactions, preserved schema, and deletion counts. Add proxy access and matching Bruno/configuration documentation. Also clear affected watched records via authenticated User Service API: full catalog clear removes all watched history; any selected movie deletion removes corresponding history. Each service accesses only its own DB. Define idempotent coordination, partial-failure recovery, and concurrent-write handling; return success only when both cleanups finish.
6. Add User DB watched table and history retrieval. Enforce ownership and chosen duplicate/date semantics; fetch movie details through Movie Service APIs. Extend User Service reset handling for the new watched table. Define stable identity and unavailable-movie behavior after Movie DB clear/reingestion.
7. Add ten avatars under `app/frontend/src/app/assets/avatars/`, default assignment, and persistent authorized avatar selection.
8. Build responsive profile UI using `app/frontend/src/app/assets/palette.json`; include watched movie cards, loading, empty, failed request, unavailable movie, and image fallback states.
9. Run relevant existing checks and focused runtime verification; update setup/service docs and task records.

Marking movies watched, filtering UI, recommendation/inference changes, and deployment work are excluded. Do not fabricate real users' watched records.

## Work Completed

- User authorized random sample watched history in user ingestion. Added `--max-watched` and VS Code input (default 10), targets 0..min(max, catalog size), including admin/existing generated users. Fetch IDs via Movie Service pagination, preserve existing history, avoid duplicate growth on reruns, and leave watched dates unknown. Zero disables seeding; empty catalog adds no history.

- Added all-history watch time beside movie count. User Service aggregates runtimes through Movie Service API in batches, preserving DB isolation; live events update the total. Display days plus remaining minutes, omit zero days, and show an em dash for missing/unavailable runtimes. Each watched movie counts once.

- Replaced timed history polling with authenticated SSE backed by PostgreSQL LISTEN/NOTIFY triggers. Direct committed writes notify the affected user; reconnect resyncs, in-flight events queue a follow-up reload, and navigation closes the stream. Nginx buffering disabled; production reserves request threads with a bounded stream count.

- Removed empty-history explanation and manual Refresh button. History refreshes quietly every 10 seconds while visible and on window/tab return; requests do not overlap and polling stops on navigation. Empty out-of-range pages return to page one.

- Removed the avatar-save confirmation and its reserved space; successful selection updates the avatar and closes the modal.

- Removed avatar-picker subtitle. User preference: short, functional UI text; avoid decorative taglines and unnecessary explanations.

- Moved avatar modal near the viewport top (24–80px responsive offset), keeping horizontal centering and internal scrolling on small screens.

- Avatar picker now uses a native modal dialog: backdrop, close button/Escape, keyboard focus containment/return, and close after successful save. Save errors remain visible inside the modal.

- Removed profile/history taglines and email from the page. Avatar now opens its picker directly, with a pencil on hover/focus and a visible edit badge on touch devices.

- Removed the profile credits footer at user request.

- Implemented the full phase in this conversation; exact session model/effort unknown, no recommendation override applied.
- Follow-up: fixed frontend launcher under POSIX sh/dash with a user npm prefix; verified exact VS Code command starts successfully.
- Catalog, ingestion, create/reuse API, reset coordination, avatar/history persistence, profile UI, local assets, startup migrations, and docs are complete.



## Validation

Completed verification (details in state.md):

- 7 Movie + 47 User + 29 frontend existing tests passed; production build passed.
- Isolated PostgreSQL/API checks and Chromium desktop/mobile checks passed.
- Live TMDB calls not run because ingestion credential is absent; offline ingestion verified.

Acceptance criteria checked:

- VS Code count prompt reaches ingestion; invalid counts fail clearly. With enough source movies, two runs of X add 2X distinct movies while retaining existing rows. Exhaustion/partial failure reports actual counts.
- Known movie resolution reuses its ID; unknown movies save required metadata; incomplete required agent data fails clearly; concurrent creation cannot duplicate source identity.
- Movie reset accepts only its configured service-local bearer token; disabled/missing configuration, invalid tokens, and invalid table selections follow existing reset behavior. Deletion preserves schema and uses service-local transactions. Movie reset also clears affected watched records through User Service API, with no direct User DB access.
- Verify full movie reset clears all watched history, selected movie deletion clears matching references, and user all/users/watched-table resets clear the expected watched state. Verify retries after partial failure, unavailable User Service, and concurrent writes; never report complete success with cleanup unfinished. Unrelated table resets preserve unrelated history. Movie clear/reingestion cannot silently reassign watched history to unrelated movies.
- With external network access unavailable, profile rendering, poster display, local movie resolution, and agent-supplied movie creation still work. No backend enrichment calls or browser image requests to external providers.
- Avatar selection persists after reload/login; invalid IDs and unauthorized updates fail.
- History persists in User DB; populated development fixtures, empty history, and unavailable movie data render correctly.
- Movie data remains owned by Movie Service; no cross-service DB reads or cross-database foreign keys.
- UI uses existing palette, supports keyboard selection, and works at narrow/wide widths with image fallbacks.
- Relevant existing frontend/backend checks pass. New tests only if separately requested.

## Next Steps

- User accepted the completed work on 2026-10-09. Agent integration and deployment remain separate work.

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
