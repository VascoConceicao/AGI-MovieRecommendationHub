# Task: Set up application structure and connect services

## Assigned To

Vasco. Coordinate inference contracts with Martim and deployment handoffs with Ricardo.

## Status

Completed.

## Goal

Establish a runnable local Angular -> Flask scaffold for the Movie, User, and Recommendation services, with dedicated database ownership and explicit Nginx and inference handoff boundaries. Runtime deployment integration remains outside the application scope.

## Context

The application stack and team responsibilities are confirmed in docs/project-spec.md and docs/ai-context.md. The repository currently contains documentation and the Forge scaffold. This task prepares and connects the application; full product features, Martim's inference implementation, and Ricardo's MLOps implementation remain outside this task.

## Todo

- [x] Define folders, runtime/package choices, health API contracts, and local configuration.
- [x] Scaffold the three Flask services and their database adapters.
- [x] Scaffold Angular and define local-development and Nginx API routing.
- [x] Verify local startup, service integration, and database failure behavior.
- [x] Document setup and inference/MLOps handoffs; record validation results.

## Plan

1. Define application layout and integration contracts.
2. Scaffold Flask services and dependency adapters.
3. Connect Angular and Nginx.
4. Verify local startup and document handoffs.

## Changes Made

- Moved each database definition into its service's db/compose.yaml, with a component-owned database launcher and root Compose includes. Preserved project, network, volume, and service settings.

- Created this task and its ordered phase plan.
- Completed the runnable application scaffold and setup documentation.
- Registered the task as Current in docs/TODO.md.
- Preserved the existing uncommitted project documentation.
- Added the missing shared Python package implementation used by all database adapters.
- Added locked npm dependencies plus service-owned Python manifests and virtual environments.
- Added Docker Compose for only the three databases running PostgreSQL 18, each bound to a distinct localhost port with its own volume and credentials.
- Added host-run Flask commands, Angular development proxy routing, and the Nginx routing handoff.
- Documented reproducible setup without machine-specific checkout paths.

## Validation

- Follow-up Compose refactor: root and all three standalone configurations validate; resolved resource settings match the previous definition. Shell syntax and repository checks pass.

- Task path and checked-out branch confirmed during helper creation.
- Task/TODO validation and Current-task resolution passed; all four phase records passed repository phase checks.
- Template files remain unchanged; git diff --check passed.
- The create-task shell validator assumes exactly one phase and rejects this four-phase plan; the repository multi-phase validator passed. No workflow helper was changed.
- Directory layout, ignore rules, project documentation validation, and whitespace checks passed.
- Full methodology validation reports executable-permission failures on five existing Forge shell helpers on Windows; required files, documentation/task structure, and plugin checks passed.
- `npm install` completed with zero reported vulnerabilities; the Angular production build passed.
- Docker Compose configuration passed and all three databases running PostgreSQL 18 became healthy.
- All three Flask health endpoints returned HTTP 200 through the Angular development proxy.
- Stopping the Movie database caused its health endpoint to return HTTP 503 with a sanitized unavailable response; restarting it restored HTTP 200.
- Local Nginx on port 4205 served the frontend and all three healthy database endpoints successfully.
- Added component-owned run scripts, individual and compound VS Code tasks, tracked-process restart and shutdown, and automatic terminal closing for database and stop tasks.

## Next Steps

- Create a separate task for product APIs, authentication/profile behavior, and the inference contract. Production deployment remains with the MLOps workstream.
