# Nginx proxy

Install locally on Ubuntu using `scripts/setup/install.sh`, then launch with `scripts/development/run.sh` from this directory. The installation and runtime files live in ignored `.runtime/`. A system-installed Nginx is also supported.

`nginx.conf` routes `/api/movie/`, `/api/recommendation/`, and `/api/user/` to the local Flask service ports. It also provides single-page-application fallback routing for built Angular assets.

`nginx.local.conf` provides a host-run development proxy on `http://127.0.0.1:4205`; it forwards the frontend to Angular on port 4204 and API paths directly to the Flask services on ports 4206 through 4208. Run it with the VS Code `run: proxy` task or `scripts/development/run-proxy.sh`. Packaging, process supervision, static-asset placement, and deployment-specific upstream addresses belong to the MLOps handoff.
