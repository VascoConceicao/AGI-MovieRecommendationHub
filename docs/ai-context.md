# AI Context

## Project Summary

Movie Recommendation Hub, PSIA group 15. Accounts, persistent login, private profile pages, avatar selection, watched-history storage, and Movie Service catalog/ingestion are implemented. Watchlists, watched actions, recommendation filters/results, and agent context APIs are implemented. Movie/user search, public profile viewing, and owner privacy controls are implemented. Prompt generation, inference, background scheduling, and interest editing remain planned. Required recommendation behavior includes a background agent preparing cached results for login.

Responsibilities: Vasco owns the app, Martim the AI/inference engine, Ricardo MLOps. Coordinate app/inference interfaces with Martim; do not assume other team responsibilities belong to Vasco.

## Technology

Angular frontend, Nginx proxy, Flask services, and three PostgreSQL databases. Use Python 3.12 and Node 24; dependency lockfiles specify exact versions. Docker Compose runs local databases; app processes run on the host. Infrastructure decisions and setup live in [infra/README.md](../infra/README.md).

## Architecture and Constraints

- Frontend → proxy → Movie, User, and Recommendation services. Recommendation Service exposes context and result APIs. Inference integration is not connected yet.
- Each service exclusively accesses its own DB. No cross-service direct DB access or cross-database foreign keys.
- Deploy containerized services to public-cloud, self-hosted Kubernetes using IaC. Managed Kubernetes is forbidden.
- Preserve current behavior and ownership boundaries. Planned features are requirements, not implemented capabilities.
- TMDB is the ingestion source; runtime movie data comes from the local catalog or complete agent-supplied payloads. External access is ingestion-only; posters are served locally. Inference contract, cache freshness, and advanced-feature selection still need agreement. Check the specification and owning task before deciding.

## Read When Needed

- [Root README](../README.md): setup, run/test commands, and plugin activation.
- [Project specification](project-spec.md): product requirements, evaluation, deadlines, and open decisions.
- [Application layout](../app/README.md) and component READMEs: structure, APIs, and local setup.
- [Task queue](TODO.md): task selection; task state/decisions/phases hold implementation details and validation.
- [Account task](tasks/authentication/0002-frontend-login-screen/state.md): completed login and related tooling.
- [Bootstrap](bootstrap.md): general agent workflow.
