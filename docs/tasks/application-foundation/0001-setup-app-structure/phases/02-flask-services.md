# Phase: Scaffold Flask services and dependency adapters

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

Create independently runnable Movie, User, and Recommendation Flask services with a minimal integration flow.

## Scope

Add configuration, health routes, and service-owned persistence wiring using the selected approach. Product HTTP dependencies and the inference substitute were deferred with the product APIs.

## Work Completed

- Added independently runnable Flask applications for Movie, Recommendation, and User services.
- Added service-owned database readiness queries and adapters using the shared bounded SQL loader.
- Added one virtual environment and pinned dependency lock per service, local configuration, and a service-aware launcher.

## Validation

- Passed: each service started on its documented localhost port and returned HTTP 200 against its own database.
- Passed: stopping the Movie database produced the documented sanitized HTTP 503 response and restarting it restored HTTP 200.

## Next Steps

- Implement product APIs and inference dependencies in a separate task after their contracts are agreed.
