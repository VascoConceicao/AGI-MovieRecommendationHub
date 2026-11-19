# Task: Movie and profile search with profile privacy

## Assigned To

Unassigned.

## Status

Completed. User accepted the implementation and requested task closure after merge to development. Current conversation used; actual model and effort not exposed, no override applied.

## Goal

Add Search next to Profile for finding movies and public user profiles. Let users control profile privacy and open movie info with Add to my list and Mark as watched actions.

## Context

- User request: search movies and users, open another user's profile, and hide private users from search.
- Existing users must become public through a data migration. New users default to public. Owners can make their profile private.
- Angular frontend and Flask services already support profiles, watchlists, watched actions, and a local movie catalog.
- Each service owns its database. Runtime search uses the local movie catalog; external movie access remains ingestion-only.
- This task covers the requested app feature. Inference, background recommendations, and other project work stay outside scope.

## Todo

- [x] Add and validate Their list, Watched movies, and Recommendations on public profiles.

- [x] Inspect current navigation, profile APIs, catalog search, movie details, and watchlist/watched actions.
- [x] Settle public profile fields, direct-link privacy behavior, and search matching/paging rules.
- [x] Add persistent profile visibility, existing-user public backfill, and public defaults for new users.
- [x] Add owner privacy control and exclude private profiles from user search in the backend.
- [x] Support opening another user's public profile without exposing account-only data or edit controls.
- [x] Add Search next to Profile, with All / Movies / Users filter buttons matching the supplied reference, movie/user results, and loading/empty/error states.
- [x] Show movie info and both buttons: Add to my list and Mark as watched. Reuse existing actions and reflect saved state.
- [x] Run relevant existing checks and verify migration, privacy, navigation, and both movie actions.
- [x] Record actual validation and update task records.

## Plan

1. Complete [implementation phase](phases/01-implementation.md): backend privacy/search, frontend flows, then validation.

## Changes Made

- 2026-10-09: Created task from docs/template, registered it as Current, and created its matching branch.
- Added one ordered implementation phase with both-provider model recommendations.
- Added requested All / Movies / Users filters using the supplied visual reference.
- User chose implementation here. Pre-phase changes: docs/TODO.md modified and new task folder untracked; retained.
- Added reusable common privacy toggle; no explanatory text below it.
- Latest scope: separate Movies and Users sections, 25 each per page, random empty search with stable order across pages. Infinite scrolling canceled by user.
- Latest loading requirement: fetch up to 1,000 per type only when needed, render 25 per page, retain only the current batch per type; no heading totals.
- Added public-profile search/read endpoints, persistent owner visibility updates, and idempotent migration 008. Applied migration to local User DB; new profiles default public.
- Added Search routes/UI, public profile view, shared movie info/actions, and matching filter buttons. Updated service/frontend docs and product context.
- Preserved parallel frontend cleanup moving My list under Profile, watchlist service under shared backend services, and movie styles under shared styles. Its changed test import was not authored by this phase.
- Fixed model/effort backticks required by the phase resolver; recommendations unchanged. Scope refinements remain within the same feature; no new model-efficiency evidence.

## Validation

- Before creation: clean tracked and untracked worktree on development.
- Global ID allocation returned 0004; creation preflight passed.
- Task helper validate and validate-todo: passed.
- Template unchanged: git diff --exit-code HEAD -- docs/template passed.
- Production build: `sh scripts/with-node.sh npm run build` from app/frontend passed (369.19 kB initial bundle).
- Existing suites: User Service 184 passed; Movie Service 117 passed; frontend 60 passed. Commands: each component's `scripts/testing/run-tests.sh --summary-only`.
- First frontend wrapper run reported FAIL during parallel report activity, despite its eventual XML showing 60 passes. Clean rerun passed. No failing test left.
- PostgreSQL: migrated all 1,001 existing profiles to public. Transactional check verified existing/new defaults and migration reruns preserving a private choice.
- Real browser smoke checks passed: privacy toggle/reload, private search exclusion/direct-link 404, public fields, owner guards, all three filters, text search, public profile navigation, empty/error/retry states, movie actions and persisted state, random-order stability/completeness, and on-demand batch boundary.
- Verified 25 visible rows/cards, zero new search fetches inside a cached batch, and one new 1,000-item request at the next user batch. Heading totals removed. Mobile width 390px had no overflow; browser reported no JS errors.
- Browser check ran with repo Node 24 launcher and existing local Chromium libraries after initial system Node 18/missing-library startup failures. Temporary check accounts and their movie state removed afterward.
- Screenshots: /tmp/g15-search-desktop.png, /tmp/g15-search-mobile.png, /tmp/g15-search-toggle.png. Smoke script: /tmp/g15-search-check.cjs; no new repository tests added.
- Final diff reviewed; `git diff --check` passed. Parallel My list/watchlist/style relocation retained; no rollback, stage, commit, or push.


### Public-profile subtabs follow-up

- User requested Their list, Watched movies, and Recommendations. Default is Their list; all three are read-only for the viewed user, 25 per page. Movie actions still target the viewer.
- Extended the public endpoint with section selection. Local collections share the visibility snapshot; recommendations use the existing service gateway and recheck privacy after the call. Public recommendation fields are allowlisted.
- Added tab loading/empty/error/retry states, keyboard navigation, pagination, and recommendation reasons. Updated public API/frontend docs.
- Validation: production build passed (375.41 kB). User Service 184 tests and frontend 60 tests passed. The frontend wrapper initially returned zero counts during report activity; the final rerun passed. Browser smoke initially checked before the tab list had loaded; corrected its wait, then passed.
- Live browser checks passed for all three populated tabs, list/recommendation pagination, viewer-only list actions, recommendation reasons, keyboard navigation, retry, mobile width, and a profile becoming private. API checks verified private profiles deny every section and privacy is checked again after the recommendation call. Temporary accounts/recommendations removed.
- Browser artifact: /tmp/g15-public-profile-tabs.png. Smoke script: /tmp/g15-public-tabs-check.cjs. No new repository tests.

### Back-link styling

- Replaced the plain underlined link with a rounded, tinted back control, SVG arrow, hover state, keyboard focus ring, and reduced-motion support. Search return parameters preserved. Production build and git diff --check passed.

### Searches in every profile section

- Added search to public Their list / Watched movies / Recommendations and own My list / Recommendations; retained the existing own Watched search.
- Searches match movie title/original title across the full section before pagination, reset offset when edited, keep recommendation source filtering, and enforce public privacy after remote reads. Public tabs retain separate query text. Missing matches and service errors have distinct feedback.
- Added owner watchlist search endpoint and shared recommendation search adapter. Updated docs. Preserved concurrent public-header/watch-time changes.
- Validation: production build passed; User Service 184 tests passed; frontend final rerun 60 passed. Two initial frontend failures expected the original argument shape for unfiltered recommendation calls; restored that shape while keeping the search timeout, then reran successfully.
- Live browser check passed for all six search fields, matches beyond page one, clearing/empty results, recommendation source filtering, mobile width, query length validation, and private-profile denial. Temporary users and recommendations removed. Script: /tmp/g15-section-search-check.cjs.
- git diff --check passed. No new repository tests or Git mutations.

### Close movie details after actions

- Add to my list and Mark as watched now close the shared details dialog after successful persistence. My list removal also closes its dialog. Errors keep the dialog open for retry; successful close restores focus in the shared dialog.
- Production build and live browser checks passed for add, watched, remove, focus restoration, and save-error behavior. Temporary account removed. Script: /tmp/g15-modal-close-check.cjs. git diff --check passed.

### Movie state actions

- Shared movie details now toggle Add to my list / Remove from my list and Mark as watched / Mark as not watched. Added shared watched-removal action, updating state and history notifications after success.
- Refresh viewer movie status on modal open; keep actions disabled until status loads. Block adding watched movies in the component; existing backend returns 409 and database constraint prevents overlapping lists. Marking watched still removes list membership. All successful actions close the modal; failures stay open for retry.
- Validation: production build, 60 frontend tests, git diff --check, and live browser checks passed. Browser verified the full state cycle, persisted changes, backend 409, disabled add, error/retry, and modal close. Temporary user removed. Script: /tmp/g15-movie-state-check.cjs.

### Hide empty search fields

- Search fields appear only when the relevant collection has items or the user has entered query text. Empty collections hide them; zero-match searches keep the field available for editing/clearing. Public subtabs retain their own known collection availability across requests. Main discovery follows the same rule.
- Validation: production build, 60 frontend tests, and live browser checks passed. Browser verified empty/populated states for all six profile sections, search retention after zero matches, clear behavior, source filtering, and privacy. Temporary accounts removed. Script: /tmp/g15-empty-search-check.cjs. git diff --check passed.

### Own recommendations heading

- Removed the own-profile Recommendations heading. Generate recommendations now occupies its place in the top row, beside the conditional search field. Kept its existing button styling and dialog behavior; public-profile headings unchanged.
- Production build and git diff --check passed.

### Default movie poster

- Added a shared local SVG poster matching the app colours. Search, profile lists, watched movies, movie dialogs, and recommendations use it when no poster is provided or loading fails. Missing recommendation metadata also gets the fallback image.
- Validation: production build, 81 existing frontend tests, built SVG asset check, and git diff --check passed. No new tests added.

### Push review

- User invoked forge:push for all current work. Reviewed search/privacy, profile navigation and avatar changes, move-to-list action, shared component relocation, poster fallback, and their tests/docs.
- Current validation: User Service 251 tests, Movie Service 119 tests, frontend 81 tests passed. Production frontend build and whitespace checks passed. Parallel test additions retained.
- Commit groups: backend APIs/migrations and tests; frontend discovery/profile UI and tests; project/task records. Normal push to origin on the current task branch requested; no history rewrite.

### Completion

- User requested marking the task done and pushing these records directly to development. Implementation merged in d7d0b0d; local task branch deleted. Latest validation: 251 User Service, 119 Movie Service, and 81 frontend tests passed; frontend build passed.

## Next Steps

- None. Task completed; implementation merged to development.
