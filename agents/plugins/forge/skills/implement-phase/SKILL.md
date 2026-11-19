---
name: implement-phase
description: Implement and review one or more ordered task phases using the active provider's recommendation and the user's choice of a native sub-agent or the current conversation. Use only when the user explicitly invokes $implement-phase in Codex or /forge:implement-phase in Claude Code, asks to implement phases with their recommendations, choose an available phase model, or retry a rejected phase.
---

# Implement Phase

Implement selected phases sequentially, either in the current conversation or with a fresh native sub-agent as the user chooses. Use only the active host and never launch another provider’s model. Work is limited to selected phases; never provider CLIs, permission bypasses, Git mutations, unrelated external writes, or concurrent worktree edits.
Resolve bundled helpers relative to this loaded skill’s directory, and pass the selected repository root explicitly. Installed resources may live in a cache; never derive or edit the project there.


## Resolve and preview

Follow repository startup. Run `sh <loaded-skill-directory>/scripts/implement-phase.sh resolve <root> [phase-name ...]`; it calls the `create-task` resolver and requires the checked-out branch to equal the selected task's complete path relative to `docs/tasks/`, preserving named order (or selecting incomplete phases by filename), skipping completed phases, validating compact recommendations, rejecting Claude `fable`, and emitting tab-separated phase, status, Codex model/effort, and Claude Code model/effort. Stop for its resolver diagnostic, branch disagreement, no phase, or incomplete recommendation. Never infer a task from a branch.

Select only the active provider's record; never translate or fall back to another provider. When refreshing recommendations, follow the [create-task model selection preference](../create-task/SKILL.md#model-selection-preference), favoring fewer total tokens while preserving response quality. Explicit user choices take precedence over that preference.

## Ask how to execute

Preview the selected phase and recommended model and effort. Unless the user already chose an execution mode for this phase or explicitly covered the selected batch, ask: “Do you want to spawn a subagent for <phase> with <model> and <effort> effort? Yes uses that subagent; no keeps working in this conversation. You can also name another model.” Wait for the answer; silence is not consent. Explain that this skill requires the choice before spawning. Ask again for a later phase only when the prior answer did not cover it. Automatic execution alone does not authorize spawning.

- **Yes:** validate the recommendation against the active native spawn interface, then spawn with that model and effort.
- **No:** implement the phase directly in this conversation with the current model and session effort. Do not spawn, switch models, or stop merely because the session differs from the recommendation or native spawning is unavailable. Report the session values when known, otherwise mark them unknown; do not claim to apply the recommended settings.
- **Another model:** treat a named replacement as the requested subagent model unless the user explicitly asks to stay in this conversation. Echo the chosen model, retain the recommended effort unless the user supplies another, validate both, and spawn without asking the same question again. If the requested values are unavailable, report supported choices and wait for a replacement or a decision to continue here; never silently substitute. A request to change the current conversation's model requires a host-supported session control; do not pretend a subagent changes it.

A temporary choice applies only to the selected phase or explicitly named batch; never rewrite stored recommendations unless requested permanently.

## Validate a requested subagent

Only the subagent path requires native spawning. Check model and effort against that tool's current schema, not a remembered or CLI catalog. In Codex, require both values and pass them as native overrides with isolated context when needed. In Claude Code, require an advertised model alias and reject unavailable/exact identifiers and `fable`; effort remains advisory unless applied through a verified native control or repository subagent frontmatter supported by the host. Otherwise it inherits the session. Check supported effort levels; if no supported override can meet the requested effort, explain the limitation and wait for a revised choice. See [Claude subagent model and effort controls](https://code.claude.com/docs/en/sub-agents).

Before spawning, report the chosen model, actually applied effort, its source, and enforcement. Distinguish the requested alias from the resolved model when the host reports it; stop for a reported substitution that conflicts with the user's choice or the prohibition on Fable. Never inspect provider CLIs or run `/model` for the user.

## Execute and review

Default to review gates. For each phase, record pre-phase `git status --short` and diff. In the subagent mode, spawn one fresh native agent and give it root, task and phase paths, selected model/effort, instructions, accepted prior results, and the scope below. In the current-conversation mode, do that work directly. Both modes have the same scope: read `AGENTS.md`, `docs/bootstrap.md`, and every task Markdown file; complete only the phase; update its status, work, validation, next steps, state, and decisions; validate; do not recursively invoke this skill, stage, commit, push, merge, rebase, switch branches, or make unrelated external writes. Review the resulting diff, records, validation, and report; then ask the user to accept, retry, or stop. Continue only after explicit acceptance.

For explicit automatic execution, retain the chosen execution mode and sequence without acceptance pauses, but wait for each successful completed phase. Obtain any execution-mode choice not already covered by the user’s instructions. Stop immediately after any failed agent, incomplete phase, unexpected diff, or validation failure. Never run agents concurrently.

On rejection, stop later phases; distinguish introduced changes from recorded pre-phase state; show the exact rollback scope; obtain approval before reverting or deleting; preserve pre-existing and accepted changes; return the phase to incomplete if needed; then apply the user’s retry choice of current conversation or an available subagent model/effort; ask the execution question if the retry mode is unspecified. Never use broad reset, checkout, clean, or stash rollback.

Afterward inspect the full diff and task records, run missing parent validation, and report execution mode, actual model, effort enforcement/advisory status, outcome, changed files, and remaining work. Do not commit or push unless the separate push workflow is invoked. Treat every agent result as requiring parent review and never hide availability, usage, permission, agent, or validation failures.
