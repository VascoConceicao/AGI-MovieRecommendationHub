---
name: swagger
description: Create or update this project's Swagger/OpenAPI docs for selected backend services or endpoints, or all APIs. Use for requested API documentation work.
---

# Swagger

Canonical docs: `app/backend/<service>-service/static/swagger.json` (OpenAPI 3.0.3). UI: `static/swagger.html`. Supported services: `movie`, `recommendation`, `user`.

Parent viewer: `app/backend/common/static/swagger.html`, packaged by `g15-common` and served by each service at `/docs/swagger.html` (proxy `/api/user/docs/swagger.html`). It fetches the service specs directly; never copy endpoint definitions into it or create a combined spec. Normal API changes require only service doc updates.

Interpret input as services and/or endpoints. `all` means all three services. Infer named routes from source; clarify only ambiguous selections. Preserve unrelated documented operations when input targets individual endpoints. This skill documents APIs; it does not authorize API behavior changes or executing requests.

Follow repository bootstrap. Resolve this skill's helpers from its loaded directory; pass the actual repository root explicitly.

1. Run `python3 <skill>/scripts/swagger.py inventory ROOT --services user` (substitute chosen services, or `all`). It inspects Flask route maps in separate processes, using service virtual environments; no endpoint is called. Read selected handlers, validation, security, persistence, and shared handlers as needed.
2. Author/update selected Swagger files from implemented behavior: paths, methods, inputs, required headers, constraints, response codes/bodies, cookie/bearer security, examples, and proxy server prefix. Include health and metrics. Exclude Flask static routes and automatic HEAD/OPTIONS. Never invent endpoints or enforce constraints removed from code. Use placeholders, never secrets. Keep descriptions short.
3. Run `python3 <skill>/scripts/swagger.py ui ROOT --services user`. It creates or refreshes the UI from the bundled template without changing API behavior. Ensure service Dockerfiles copy `static/`; Flask already serves it. UI uses pinned CDN assets, so internet is needed to load the viewer.
4. Validate with `uv run --with openapi-spec-validator==0.7.2 --python 3.12 <skill>/scripts/swagger.py validate ROOT --services user`, or run with an interpreter having that package. Validation checks OpenAPI semantics and exact method/path coverage against Flask. Fix missing/stale operations; for a narrow request, preserve unaffected operation details.
5. Verify static docs serve through Flask/proxy and the viewer renders. GETs are enough; do not run registration, logout, reset, or other mutations just to check docs. Run `git diff --check`; report docs URLs and scope.

`--services all` selects every service; multiple names select several. Examples: `$swagger all`, `$swagger user`, `$swagger user /auth/register`.
