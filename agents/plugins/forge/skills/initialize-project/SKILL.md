---
name: initialize-project
description: Interview the user and personalize a generic project scaffold by updating README.md, docs/project-spec.md, docs/ai-context.md, and any relevant project instructions with accurate project-specific information. Use when starting, bootstrapping, onboarding, or repurposing a repository whose documentation contains placeholders or generic content, or when the user asks to describe a project and fill its documentation.
---

# Initialize Project

Turn generic documentation into an accurate project foundation. First run `sh <loaded-skill-directory>/scripts/project-docs.sh inspect <root>` from the repository root; it deterministically reports the three required project documents. Then read repository instructions, those documents, and relevant tree, manifests, lockfiles, configuration, and source as evidence. Existing code can conflict with docs; placeholder text is not evidence.
Resolve bundled helpers relative to this loaded skill’s directory, and pass the selected repository root explicitly. Installed resources may live in a cache; never derive or edit the project there.


## Check Forge activation

Before the interview, check both Codex and Claude Code when available, respecting any host selection already made by the user. For each host, read the selected repository’s catalog name and confirm its `forge` entry resolves to this repository’s `agents/plugins/forge/`. Use `codex plugin list` and `claude plugin list` from the project root to check the exact `forge@<catalog-name>` installation and enabled status; confirm Claude’s project scope. These are management commands, not model sessions. If a CLI is unavailable, inspect the active host’s plugin UI/tools when possible and report unverified status otherwise. Do not install a provider CLI just to check it.

Packaged files and successful repository validation do not prove host activation. Report packaged, installed, enabled, and session-loaded status separately. Verify loaded skills against the active session’s skill catalog; another host’s invocation remains unverified until observed. Check installed resources against project sources when a stale cache is suspected.

For missing activation, use the repository’s linked plugin setup guide to register the exact local marketplace and install Forge (Claude: `--scope project`). Honor existing authorization; when setup is not authorized, explain the missing step and ask only for that host change. Preserve intentionally disabled plugins and other projects’ sources; do not silently switch them. Recheck status after any setup or refresh. An unavailable host or failed setup must not block independent documentation work, but remains an explicit outstanding item. After installation/refresh, tell the user to start a new Codex thread or reload/start a Claude session before checking the skill picker or `/forge:initialize-project`.

Keep host inspection and setup agent-directed: host UI availability, CLI output, session catalogs, and authorization differ between environments, so a portable script cannot safely determine or repair every activation state. Do not edit host configuration or installed caches directly, create loose skill aliases, or launch model sessions as a discovery test.

## Interview and reconcile

Ask only for material facts unavailable from the repository, in related groups of at most three. Start with name, purpose/problem, and users; then collect any missing stage/capabilities, goals/non-goals/requirements/success criteria, stack/architecture/versions/package manager, commands, constraints/conventions/services, contribution workflow, and license. Accept partial answers. Record an undecided material fact as `Not yet decided` or an open question; distinguish recommendations from confirmed decisions. Reconcile answers with evidence before editing: ask about material contradictions and use conservative wording for minor gaps.

Maintain one consistent fact set: identity; product stage, features, goals, non-goals, and success criteria; engineering stack, architecture, commands, conventions, and services; and governance constraints, contribution workflow, and license.

## Update and validate

Update only project-specific content after reviewing repository documentation and instructions:

- `README.md`: approachable overview, status, capabilities, setup/usage/development/testing, documentation, contribution, and license.
- `docs/project-spec.md`: problem, users, goals/non-goals, functional/quality requirements, constraints, success criteria, and open questions.
- `docs/ai-context.md`: agent-useful stack, architecture, commands, conventions, constraints, and services.
- Preserve general workflow in `AGENTS.md`/`docs/bootstrap.md`; change it only for stable user-supplied agent or development rules. Keep task guidance/templates reusable unless project task conventions differ. Never create a task folder without an explicit request.

Preserve useful user content, valid links, and unrelated changes. Never invent commands, dependencies, versions, services, or a license. Remove known template markers after values are known; omit irrelevant sections and state material unknowns explicitly.

Run `sh <loaded-skill-directory>/scripts/project-docs.sh validate <root>` from the repository root after editing. Its placeholder contract reports `{{TODO: ...}}`, generic starter prose such as `<Describe ...>` outside fences, `<Project Name>`, and `*-command` lines such as `<test-command>` inside fences; it deliberately ignores other angle-bracket syntax so intentional examples are not false positives. Also reread changed files for consistency, search stale prior identity when repurposing, run `git diff --check`, inspect the full documentation diff, and run repository documentation checks. Report files, recorded facts, validation, and unresolved questions; do not claim completion with required markers or material contradictions.
