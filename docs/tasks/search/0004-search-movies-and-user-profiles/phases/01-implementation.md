# Phase: Implement search, profile privacy, and movie actions

## Status

Completed and accepted by the user. Implementation merged to development. Current conversation used; actual model/effort not exposed and no override applied.

## Recommended Model

### Codex

- Model: `gpt-6.1-sol`
- Effort: `medium`

### Claude Code

- Model: `sonnet` (access and alias version Unverified)
- Effort: `medium` (advisory)

## Goal

Deliver Search next to Profile: find movies and public users, view another user's profile, manage own privacy, and open movie info with both requested actions.

## Scope

1. Inspect existing APIs, migration conventions, navigation, profile views, and movie actions. Settle pending public fields, direct-link privacy, and search rules before dependent changes.
2. Backend: store profile visibility; backfill existing users to public without losing account data; default new users to public; allow owner privacy updates; exclude private users from search. Provide public profile reads using only agreed fields. Keep owner access and service boundaries intact.
3. Frontend: add Search beside Profile, search movies/users with All / Movies / Users filter buttons matching the supplied reference, open public profiles with Their list / Watched movies / Recommendations, and add own-profile privacy control using a reusable common toggle with no bottom text. Keep separate Movies and Users sections, 25 each per page with no heading totals. Fetch batches of up to 1,000 per type only when the requested page needs them; cache only the current batch per type. Empty search uses stable seeded random order and covers the full catalog/public users through page buttons; no infinite scroll. Movie details show info, Add to my list, and Mark as watched using existing persistence. Handle loading, empty results, errors, and saved action state.
4. Validation: run relevant existing checks and manually verify the full flows. Record actual results and remaining limits.

Outside scope: inference, background recommendation generation, new ingestion sources, and unrelated account/profile features. New test creation was not requested.

## Work Completed

- Added migration 008, own-profile visibility update, public-user search and public profile/history reads. Private profiles excluded by backend and return 404 on direct links.
- Added Search next to Profile, requested type filters, separate paginated sections, stable random empty browsing, and 1,000-item on-demand batches.
- Added reusable common privacy toggle without bottom text, public profile view, and reusable movie result/details UI with both persisted actions.
- Updated docs and task decisions. Existing parallel folder cleanup preserved.

## Validation

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

## Remaining Limits

- Stable page ordering assumes unchanged catalog/profile visibility during the browse. In-memory search batches are snapshots; a fresh search visit/retry refreshes them. Direct profile reads always recheck privacy.
- Offset ceiling remains the existing 1,000,000 convention. New repository tests were not requested; existing suites and live browser/PostgreSQL checks used.

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

## Next Steps

- None. Phase accepted; task completed.
