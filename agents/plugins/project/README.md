# Project Plugin

Project-specific skills. Separate from Forge workflow skills.

## Swagger

Source: `skills/swagger/SKILL.md`.

- All APIs: `$swagger all`.
- One service: `$swagger user` (also `movie` or `recommendation`).
- One endpoint: `$swagger user /auth/register`.
- Claude Code: `/project:swagger` with the same input.

Creates/updates each selected service's `static/swagger.json` and `static/swagger.html`. Checks OpenAPI validity and Flask route coverage. Does not execute API mutations.

## Activation

The repository Codex and Claude marketplaces include `project` alongside `forge`. Install/enable `project` from this repository's existing catalog (`forge-31735840701578f5`), then start a new session. Claude project install: `claude plugin install project@forge-31735840701578f5 --scope project`.

Source packaging does not prove host installation, enablement, or session loading. These host steps remain separate. Future project skills belong here; Forge remains the shared workflow plugin.
