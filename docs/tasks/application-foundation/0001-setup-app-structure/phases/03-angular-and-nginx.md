# Phase: Connect Angular and Nginx

## Status

Completed.

## Recommended Model

### Codex

- Model: gpt-5.6-terra
- Effort: medium

### Claude Code

- Model: sonnet (Unverified)
- Effort: high (advisory)

## Goal

Connect the Angular application shell to the three Flask services through Nginx.

## Scope

Add Angular health clients, local same-origin development routing, and the equivalent Nginx API routing handoff. Product recommendation behavior and production cloud ingress are excluded.

## Work Completed

- Added the Angular connection-status page and typed health client for all three services.
- Added a local Angular development proxy for host-run Flask services.
- Added equivalent Nginx route definitions as a deployment handoff without containerizing or running Nginx.
- Added the npm lockfile and start/build commands.

## Validation

- Passed: Angular production and local-development builds.
- Passed: all three API routes through the Angular development proxy.
- Nginx runtime validation is assigned to the deployment workstream; the application routing contract is documented.

## Next Steps

- Use the routing handoff when deployment packaging begins.
