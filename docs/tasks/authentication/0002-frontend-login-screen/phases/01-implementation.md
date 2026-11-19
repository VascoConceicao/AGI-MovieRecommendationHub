# Phase: Implement login screen and registration

## Status

Completed.

## Recommended Model

### Codex

- Model: `gpt-6-astra`
- Effort: `medium`

### Claude Code

- Model: `sonnet` — Unverified
- Effort: `medium` — advisory

## Goal

Deliver persistent login/registration and the user-approved follow-up tooling recorded in `../decisions.md`.

## Scope

Initial scope: responsive Angular account screens, User Service authentication, and three User DB tables. Follow-ups: UI simplification, unique usernames, resets/Bruno, service env files, configurable ingestion, Swagger viewers, project skills, automated tests, script organization, and shared frontend HTTP logic. Movie/recommendation features remain outside this task.

## Work Completed

- Implemented transactional account/profile/session creation, Argon2id passwords, login/logout/current-user endpoints, seven-day sessions, cookies, and request validation.
- Added username migration/backfill and DB-enforced case-insensitive username/email uniqueness. Registration includes username and displays distinct duplicate errors.
- Applied palette, removed group branding/posters/extra copy, centered story text, set desktop 40/60 panels, and made “Create your account” fit one line. Simplified browser title. Removed password minimum length while retaining confirmation.
- Added opt-in all/single-table reset endpoint and four named Bruno requests using built-in Bearer auth and JSON bodies.
- Moved all local settings into service env files; removed root env/example and updated Compose/launchers.
- Added `db/ingestion`, JSON template assets, count prompt task, extra admin account, profiles without sessions, and ignored credential export.
- Added per-service Swagger files and parent common/static viewer reading all three specs. Flattened common into named folders.
- Created separate `project` plugin with Swagger, run-tests, and create-tests skills; validated source packaging.
- Added component test runners, root aggregate runner, coverage JSON/HTML/tables, mirrored Python test folders, adjacent Angular specs, and VS Code task.
- Organized root/app scripts into purpose folders. Removed common/scripts and moved common test entrypoint to root.
- Grouped frontend backend services and extracted injected BackendService for shared HTTP/timeouts, preserving domain state, routes, validation, and headers.
- Updated setup, schema/API, workflow, and task docs; kept unrelated existing work intact.

## Validation

Full suite rerun on 5 October 2026. No failed or skipped tests.

| Component | Passed | Lines | Branches |
| --- | ---: | ---: | ---: |
| scripts | 12 | 31.9% | 20.3% |
| common | 7 | 100.0% | 100.0% |
| movie | 7 | 100.0% | 100.0% |
| recommendation | 7 | 100.0% | 100.0% |
| user | 47 | 70.3% | 63.4% |
| frontend | 29 | 92.0% | 88.6% |
| **Total** | **109** | **59.2%** | **51.3%** |

- Frontend production builds passed, including the final BackendService refactor.
- Browser checks passed for registration/login/logout, session reload persistence, protected routes, duplicate messages, and responsive/single-line heading layout.
- DB/API checks passed for schema initialization/backfill, unique identity constraints, passwords, session expiry/logout, and request protection. Reset verified against a disposable DB.
- Ingestion and ignored credentials verified with 1,000 samples plus admin and no sessions; reruns were idempotent.
- OpenAPI specs match service routes; parent tabs and packaged common static files verified.
- Relocated app launchers start frontend/proxy/all services; all three DBs healthy. Task paths and shell syntax valid.
- Skills, methodology, and whitespace checks pass. Coverage gaps remain visible; 100% was not claimed.

## Next Steps

Phase complete. Use root test runner for totals, refresh project plugin to load skills, and track future product/coverage work separately.
