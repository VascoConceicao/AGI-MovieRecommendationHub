# Application layout

```text
app/
  frontend/
  backend/
    common/
    movie-service/
    recommendation-service/
    user-service/
  proxy/
```

This layout provides health checks, accounts, private profiles with avatars/history, and a local movie catalog with ingestion. Watchlists, watched actions, recommendation filters/results, and agent context APIs are available. Inference and background generation remain later work. Empty directories reserved for later product work use `.gitkeep` so they survive a checkout.

Every runnable component and the shared backend library has a local `.gitignore` for its own dependencies, environments, caches, logs, and build output. Each Python component also owns its `.python-version`; the frontend owns its Node version through `.nvmrc`. The repository-level ignore file remains the final safety net.

See [frontend](frontend/README.md), [Movie Service](backend/movie-service/README.md), [Recommendation Service](backend/recommendation-service/README.md), [User Service](backend/user-service/README.md), [shared backend library](backend/common/README.md), and [proxy](proxy/README.md) for ownership and planned entry points.

Each backend service owns `db/sql/`, `db/migrations/`, and `db/seeds/`. Runtime database data lives in persistent volumes, outside Git. Cross-service access goes through service APIs.

Each service also owns its database-only `db/compose.yaml` and `scripts/database/run-db.sh`. The root Compose file includes all three definitions. Root and standalone commands share one project name and the same volumes.

The local stack uses Python 3.12, Flask 3.1.3, Psycopg 3.3.6, Node.js 24, Angular 21.2, npm, and three dedicated PostgreSQL 18 databases. Docker Compose runs only the databases; Flask and Angular run on the host. See the root README for startup commands.
