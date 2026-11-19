---
name: create-tests
description: Create meaningful g15 tests from measured coverage gaps for requested files, functions, components, services, or the whole project. With no narrower input, target 100% coverage for all application code.
---

# Create Tests

Read the target component’s test configuration and run `<repo>/scripts/testing/run-tests.sh` first. Resolve user scope: named files/functions/features or target percentages narrow the work. Without narrower input, cover the entire measured project until every executable file reaches 100% lines and branches; frontend functions/statements must also reach 100% in its raw Vitest reports.

Use fresh component `coverage/coverage.json` (Python missing lines/branches), frontend `coverage/frontend/coverage-final.json` and `coverage-summary.json`, root `coverage/scripts/coverage.json`, and source code to find gaps. Locate frontend reports recursively under `coverage/` if the CLI project name changes.

Put Python tests in the owning component's `tests/`, mirroring source folders: `api/auth.py` → `tests/api/test_auth.py`, `services/accounts.py` → `tests/services/test_accounts.py`, `db/ingestion/users.py` → `tests/db/ingestion/test_users.py`; root `main.py` → `tests/test_main.py`. Root helper tests mirror script subfolders under root `tests/scripts/`. Put Angular `*.spec.ts` next to the tested component/service, with each service in its own folder. Add behavioral assertions for missing paths, boundaries, errors, and interactions. Mock external boundaries or use disposable fixtures; never clear or seed the running app DB. Do not call real services merely to satisfy coverage.

Run affected `scripts/testing/run-tests.sh` after each useful batch; common helpers use root `scripts/testing/test-common.sh`. Repeat while requested gaps remain, then run the whole project through the root runner.

Do not increase percentages by weakening tests, adding coverage ignores, removing source from coverage, skipping failures, or deleting behavior. A discovered application defect may be fixed within the requested scope; preserve intended behavior and explain it. If a target is unreachable without a user decision or external requirement, report the remaining gap and cause honestly; do not claim 100% or keep retrying the same blocker.

Report only coverage/test totals in chat, with brief changes and any blockers. Per-file detail stays in generated reports unless the user specifically asks for it.
