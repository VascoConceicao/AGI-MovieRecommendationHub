# Shared backend code

```text
common/
  db/          SQL file loader
  monitoring/  Request counts, response times, database health
  docs/        Shared Swagger viewer serving code
  static/      Parent Swagger HTML
```

`db/query_loader.py` reads SQL files safely. Queries and database connections stay inside each owning service.

`monitoring/metrics.py` exposes `/metrics` for Prometheus and records request counts/timing. It also tracks whether each database is reachable.

`docs/api_docs.py` serves `static/swagger.html` at `/docs/swagger.html`. Open `http://127.0.0.1:4205/api/user/docs/swagger.html`. Three tabs load the existing service specs directly; no copied API definitions. The viewer reads the frontend palette at `/assets/palette.json` and uses pinned Swagger UI CDN assets.

Each Flask service installs this folder with:

```sh
SERVICE/.venv/bin/python -m pip install -e app/backend/common
```

The Python import name stays `g15_common`, mapped directly to this folder by `pyproject.toml`; no `src/g15_common` directory is needed. Static HTML is included in the built package for containers.
