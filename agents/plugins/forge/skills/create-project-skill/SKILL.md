---
name: create-project-skill
description: Create or update a repository-local Agent Skill and package its canonical source in the forge plugin for Codex and Claude Code. Use when the user asks to add, scaffold, author, or revise a local project skill that should be shared across supported coding agents.
---

# Create Project Skill

Maintain one editable source at `agents/plugins/forge/skills/<skill-name>/`; include it in the project’s `forge` plugin for both hosts. Keep all resources inside the plugin.

## Workflow

1. Infer or confirm a unique lowercase hyphenated name, purpose, triggers, and resources. Ask only what cannot be inferred. Reusing a project, user, system, or plugin skill name requires explicit override.

2. Use the available `skill-creator` and its complete workflow. Include only necessary resources, preserve useful existing ones, and generate `agents/openai.yaml` (refresh stale interface metadata).

3. Before validation, reread the entire skill and condense its instructions to the shortest clear form to reduce token usage. Remove repetition and obvious explanations; merge equivalent rules. Preserve behavior, distinct triggers, permission boundaries, and outcomes.

4. Put every deterministic, portable, testable mechanic in a project-local script, leaving its invocation and decision contract in `SKILL.md`. Beside any exception, concisely state why code is unsafe, nonportable, or not meaningfully testable.

5. Validate package membership using the helper beside the loaded skill (substitute its actual resource path and the explicitly selected project root):

```sh
sh <loaded-skill-directory>/scripts/package-skill.sh <skill-name> <repository-root>
sh <loaded-skill-directory>/scripts/package-skill.sh validate <skill-name> <repository-root>
```

The helper validates both manifests/catalogs, contained resources, no loose duplicate, and shell syntax/modes. It never edits host settings, creates discovery aliases, or adds project-created skills to Forge’s managed ledger.

6. Confirm plugin source changes in `git status`; report membership validation and the refresh handoff below.

## Discovery and safety

- Author only in the selected repository’s `agents/plugins/forge/skills/`; never edit an installed plugin cache.
- Resolve bundled helpers from the loaded skill location and pass the target repository explicitly. Do not infer the project from a cached resource path.
- Both hosts require plugin activation and refresh after source changes/new skills; follow the project README. Report packaged, installed, enabled, and session-loaded status separately.
- Codex: select this project’s `forge` source, refresh the local cachebuster and reinstall, then start a new thread. Other projects’ same-named plugins may need disabling; automatic project isolation is unverified.
- Claude Code: invoke `/forge:<skill-name>` after project-scope install; bump its plugin version, update the install, then reload/start a session.
- Never create loose discovery copies/links, replace conflicting paths, or delete user skills during packaging.
