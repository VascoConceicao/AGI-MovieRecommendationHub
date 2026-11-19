# Phase: Define application layout and integration contracts

## Status

Completed.

## Recommended Model

### Codex

- Model: `gpt-5.6-terra`
- Effort: `medium`

### Claude Code

- Model: `sonnet` (Unverified)
- Effort: `medium` (advisory)

## Goal

Define frontend, service, proxy, configuration, and local development folders and explicit service contracts.

## Scope

Document API prefixes, service addresses, health endpoints, database ownership, and inference request/response boundaries. Resolve versions, package managers, database approach, and local orchestration before dependent implementation.

## Work Completed

- Created the agreed directory scaffold and documented planned entry points without adding nonfunctional launch scripts.
- Added ignore rules for local application artifacts.
- Corrected recommendation formatting so the phase resolver passes.
- Execution: current conversation, per user choice; actual model identifier and effort unknown, no override applied.
- Selected Python 3.12, Flask 3.1.3, Psycopg 3.3.6, Angular 21.2, Node 24, npm, pip, and three databases running PostgreSQL 18.
- Defined local ports, health contracts, database ownership, environment configuration, and database-only Docker Compose orchestration.

## Validation

- Passed: directory ownership/layout assertions, representative Git ignore checks, project documentation validation, and git diff --check.
- Full methodology validation passed required files, documentation/task structure, and plugin checks, but failed executable-permission checks on five existing Forge shell helpers on Windows. Helpers were not changed.
- Validation required Git Bash on PATH and a shell-local python3 function targeting installed Python 3.12; initial Windows PATH/alias failures were resolved for these checks.
- Health contracts and runtime choices are implemented and verified. Product and inference contracts are intentionally deferred.

## Next Steps

- Continue product and inference contract design in a separate task.

## Scope Update and Handoff

The user selected Docker-hosted PostgreSQL and delegated version choices. The selected stack is PostgreSQL 18, Python 3.12, Flask 3.1.3, Psycopg 3.3.6, Angular 21.2, Node 24 LTS, pip, and npm. Docker is limited to the three databases; Flask and Angular run on the development host.

The health-only implementation, dependency installation, builds, local routing, database startup, failure response, and recovery are verified. Product APIs, inference implementation, and deployment packaging remain separate workstreams.
