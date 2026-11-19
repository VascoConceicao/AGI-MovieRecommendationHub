# Decisions

## Confirmed

- Frontend: Angular. Reverse proxy: Nginx. Domain services: Flask (Python).
- Vasco owns application work; Martim owns AI/inference; Ricardo owns MLOps.
- Each backend service owns a dedicated database instance, with no cross-service database access.
- Scope is application foundation and integration, not complete account/profile/recommendation features or cloud infrastructure.
- Keep inference behind a documented adapter. A clearly labeled development substitute may support local wiring without implementing Martim's model.
- Task branch: application-foundation/0001-setup-app-structure, created from development. Existing documentation edits are preserved under the user's direction to create the task records.
- Phase recommendations are advisory. Native Codex supports gpt-5.6-terra; Claude sonnet availability is Unverified and effort is advisory. Comparative total-token efficiency is unknown; no efficiency ranking is claimed.

- User confirmed the source layout in [app/README.md](../../../../app/README.md): frontend, backend/common, three backend services, and proxy.
- Each service uses api, helpers, models, services, db/sql, db/migrations, db/seeds, static, and tests. Database runtime data stays outside Git.
- Frontend shared folders: config, constants, fixtures, security, services, types, utils, plus index.ts. Translation assets live beside shared under translations/assets.
- Shared backend utilities will form an installable library; service-specific SQL, connections, credentials, and domain logic remain service-owned.
- User chose current-conversation execution for phase 01; no subagent or model override applied. Actual model identifier and session effort are not exposed.

- User selected PostgreSQL in Docker, one dedicated instance per backend service; PostgreSQL 18 is the chosen major version.
- Selected Python 3.12, Flask 3.1.3, Psycopg 3.3.6, Angular 21.2, Node 24 LTS, pip, and npm. Dependency installation, lockfiles, and builds are verified.
- Current integration scope is frontend health checks through each backend to its own database. Product API contracts and inference integration are explicitly deferred by the user.
- Docker Compose is used only for the three databases running PostgreSQL 18. Flask, Angular and the development Nginx proxy run on the host. Production packaging belongs to the deployment workstream.
- Each runnable component owns scripts/development/run.sh; VS Code tasks invoke those scripts and run: app starts all components. Ports are frontend 4204, proxy 4205, Movie 4206, Recommendation 4207, User 4208.
- Each Python service owns its requirements, lockfile, .venv, .python-version and .gitignore. The shared library owns its version and ignore declarations, but has no server process.
- Do not record machine-specific checkout paths in project documentation.

## Database Configuration Follow-up

- Each backend service owns its database-only db/compose.yaml and scripts/database/run-db.sh; the root compose.yaml includes all three.
- Standalone and root operations use the same g15-databases project and persistent volumes. Root .env remains the shared local configuration source.
- Resolved service, network and volume configuration matches the previous monolithic definition. No database recreation or data migration was needed for this change.

## Pending

- Application schemas and product API contracts.
- Inference integration, including the request/response protocol with Martim's engine.
- Production deployment packaging with Ricardo.
- Background agent integration boundary; this task does not implement full proactive recommendation behavior.
