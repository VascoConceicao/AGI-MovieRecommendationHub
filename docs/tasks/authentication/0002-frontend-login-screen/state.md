# Task: Frontend login screen

## Assigned To

Unassigned.

## Status

Completed.

## Goal

Deliver palette-based login/registration with persistent accounts, profiles, and sessions. Include the requested follow-up DB tools, API docs, test runners, and project skills.

## Context

User-approved follow-ups expanded this task after the initial login implementation. Final behavior and layout are recorded in `decisions.md`; implementation evidence is in `phases/01-implementation.md`. Movie discovery, watched history, and recommendations remain future work.

## Todo

- [x] Create User DB accounts, profiles, and sessions; implement registration, login, session lookup, and logout.
- [x] Apply the supplied palette and requested copy/layout refinements.
- [x] Enforce unique usernames and emails in DB; show clear duplicate errors in registration.
- [x] Add all/single-table resets and four Bruno requests using Bearer auth.
- [x] Create service-owned local `.env` files and remove the root env.
- [x] Add configurable user ingestion, JSON templates, admin account, and ignored login export.
- [x] Add service Swagger files and the shared three-tab viewer.
- [x] Create project `swagger`, `run-tests`, and `create-tests` skills.
- [x] Add component test runners, mirrored Python tests, adjacent Angular specs, and coverage totals.
- [x] Organize script folders and extract shared frontend BackendService.
- [x] Verify builds, browser behavior, APIs, tests, and documentation.

## Plan

Implementation and user-requested follow-ups completed in `phases/01-implementation.md`.

## Changes Made

- User Service owns `users`, `user_profiles`, and `user_sessions`. Startup applies both migrations transactionally; existing accounts receive unique usernames. Passwords use Argon2id; seven-day sessions store hashed tokens and use HttpOnly cookies.
- `/login`, `/register`, `/account`, and `/health` implemented. Registration includes username, display name, email, password, and confirmation. DB uniqueness ignores case; duplicate messages are “Username already exists.” and “Email already exists.”
- Palette saved in frontend assets; styling follows the task decision. Removed group-number branding, decorative posters, and requested extra copy. Desktop panels are 40% story / 60% form; left text is centered. “Create your account” scales to stay on one line. Browser title is “Movie Recommendation Hub”. Password minimum-length policy removed; nonempty password and confirmation remain.
- Opt-in `/api/user/admin/reset-user-db` accepts `all`, `users`, `user_profiles`, or `user_sessions`. Bruno `DBs/Clear/User` contains All, Sessions, Users, Profiles, with JSON bodies and `{{resetToken}}` in Auth → Bearer Token; no manual headers.
- Each backend service has its own ignored `.env` for API and DB settings. Root `.env` and example removed; Compose and launchers use service files. User local reset enabled with a private static token; local cookies allow HTTP.
- Ingestion lives in `user-service/db/ingestion`. VS Code `ingest: users` prompts for sample count. Admin `admin@admin.com` / `admin` is extra, without permission roles. JSON assets generate repeatable names, unique usernames/emails, and sample passwords. Creates profiles, no sessions. Initial credentials export to ignored `.run/ingestion-users.csv`.
- Each service owns `static/swagger.json` and its viewer. Shared parent is `backend/common/static/swagger.html`, served at `/api/user/docs/swagger.html`; tabs read service specs directly. Common code is organized into `db`, `monitoring`, `docs`, and `static`, without `src/g15_common`.
- Repository-local plugin `project` contains Swagger and testing skills for both hosts. Source packaged and validated; refresh/install plus a new session is needed to load new skills.
- Root `scripts/testing/run-tests.sh` calls all suites and reports component/overall totals. Component runners print per-file coverage; VS Code task is `test: all`. Python tests mirror source folders; Angular specs are adjacent. All script folders are grouped by purpose. `backend/common/scripts` was removed entirely.
- Frontend shared services are under `shared/services/backend`, with `auth/` and `health/` folders. BackendService centralizes typed HTTP requests, headers, and timeouts; domain services keep routes, payloads, state, and response handling.

## Validation

Latest full run on 5 October 2026: all tests passed; none failed or skipped. Totals are weighted by executable lines/branches, not averaged percentages.

| Component | Passed | Lines | Branches |
| --- | ---: | ---: | ---: |
| scripts | 12 | 31.9% | 20.3% |
| common | 7 | 100.0% | 100.0% |
| movie | 7 | 100.0% | 100.0% |
| recommendation | 7 | 100.0% | 100.0% |
| user | 47 | 70.3% | 63.4% |
| frontend | 29 | 92.0% | 88.6% |
| **Total** | **109** | **59.2%** | **51.3%** |

- Latest frontend production build passed. Browser checks verified account flows, duplicate username/email feedback, session persistence, and one-line registration title without overflow at 320–1920px.
- Live DB/API checks verified persistence, password hashes, case-insensitive uniqueness, migrations, session expiry, logout, and request protection. Reset modes were tested in a temporary DB.
- Ingestion verified 1,000 sample users plus admin, matching profiles, exported credentials, and zero seed sessions; rerun skipped existing samples.
- Swagger specs validate and match Flask routes; parent tabs read live specs. Shared viewer also verified from an installed common wheel.
- Relocated launchers restarted all five app components; all three DB health checks passed. VS Code paths and shell syntax verified.
- Project skills, repository methodology, and `git diff --check` pass.
- Coverage still has gaps; 100% is the default target of a future unscoped `create-tests` request, not a claimed result of this task.

## Next Steps

- Use VS Code `test: all` or `sh scripts/testing/run-tests.sh` for current totals.
- Refresh the project plugin before invoking its new skills. Use `create-tests` for scoped gaps or the default full-coverage target.
- Future product work: movie discovery, profile preferences, watched history, recommendations, login throttling, and password recovery.
