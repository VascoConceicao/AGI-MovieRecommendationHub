---
name: run-tests
description: Run the entire g15 project test suite and report coverage totals. Use when asked to run project tests or check coverage; does not create tests or change application behavior.
---

# Run Tests

Resolve the target repository, then run:

```sh
sh <repo>/scripts/testing/run-tests.sh
```

The runner calls root scripts, common, Movie, Recommendation, User, and frontend scripts, continues after failures, and exits nonzero if any suite fails. It does not load app `.env` files or reset databases.

If dependencies are missing, install Python components’ `requirements-test.lock` and frontend locked dependencies. Common owns the Python environment for root-script tests. Do not interpret missing reports as zero or successful coverage.

Read fresh `<repo>/coverage/summary.json`. Reply with totals only: component, passed/failed/skipped tests, line and branch coverage, plus the combined totals. Combined coverage is weighted by executable lines/branches, not averaged percentages. For failures, name the suite and link its `coverage/test-output.log`; no per-file table in chat.

Detailed coverage lives under each component's ignored `coverage/`; root script reports use `coverage/scripts/`. Inspect those reports only to explain a failure or requested gap. This skill runs tests; test creation belongs to `create-tests`.
