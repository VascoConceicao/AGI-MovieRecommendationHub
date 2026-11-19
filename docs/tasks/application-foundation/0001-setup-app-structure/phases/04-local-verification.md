# Phase: Verify local startup and document handoffs

## Status

Completed.

## Recommended Model

### Codex

- Model: gpt-5.6-terra
- Effort: high

### Claude Code

- Model: sonnet (Unverified)
- Effort: high (advisory)

## Goal

Provide reproducible local startup and verify the complete integration path.

## Scope

Document environment examples, startup commands, the inference adapter handoff for Martim, and runtime/configuration handoffs for Ricardo. Use the selected local execution approach; no cloud deployment or MLOps pipeline implementation.

## Work Completed

- Documented dependency installation, database startup, host-run Flask services, Angular startup, build, health checks, and shutdown.
- Documented the inference adapter boundary for Martim and the Nginx/deployment boundary for Ricardo.
- Kept Docker limited to the three local databases.

## Validation

- Task restart follow-up: launching the Movie component twice stopped the first process and restored a healthy endpoint on 4206. VS Code tasks supervise component launchers and database recreation preserves volumes.

- Follow-up: component-owned launchers verified with separate service virtual environments. Local Nginx installed from Ubuntu packages into ignored proxy runtime; frontend and all three database health requests passed through port 4205. VS Code tasks use these launchers; editor UI execution is not available in this session.

- Passed: Compose validation, database health, Python compilation/import, npm dependency audit, Angular build, frontend availability, and all three health requests.
- Passed: database-unavailable and recovery behavior for the Movie service.
- Inference behavior is deferred until its contract exists; Nginx runtime validation belongs to deployment packaging.

## Next Steps

- Begin product behavior in a new tracked task.
