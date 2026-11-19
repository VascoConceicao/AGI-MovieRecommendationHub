---
name: create-task
description: Create, register, organize, or open a tracked project task with a hierarchical task path and TODO-based selection. Use for an explicit new-task request or an explicit request to select, switch, or locally reorganize a tracked task; do not invoke for ordinary implementation.
---

# Create Task

Use `scripts/task-helper.sh` for deterministic validation, IDs, branch checks, staged creation, TODO resolution, and moves; it owns task grammar.

Follow startup; use `docs/template/`. Use request and repository facts; honor a supplied valid name, otherwise derive a lowercase-hyphenated slug, use `Unassigned`, choose discovery for unclear work or implementation for concrete work, and leave unstated requirements, decisions, and validation pending.
Resolve bundled helpers relative to this loaded skill’s directory, and pass the selected repository root explicitly. Installed resources may live in a cache; never derive or edit the project there.


## Plan

Use exactly two compact, read-only native subagents when the host supports them.

- Placement: inspect only candidate direct sibling folder names and their `state.md` Title, Status, and Goal; return `{leaf, confidence, ambiguity, move_plan?}`. Choose the deepest stable semantic leaf. For a new subgroup, consider only direct children of its immediate parent. Never read sibling decisions, phases, history, source, cousins, or deeper branches.
- Draft: return `{title, goal, phases:[{name,goal,codex:{model,effort},claude:{model,effort}}]}`. Keep both-provider recommendations; discover supported native models, mark unavailable cross-provider choices `Unverified`, and never recommend Claude `fable`.

Use current [Codex model guidance](https://learn.chatgpt.com/docs/models) and [Claude model configuration](https://code.claude.com/docs/en/model-config) to assess newly available models and alias versions; native tool availability remains authoritative. Claude alias versions depend on provider and configuration, so documentation alone does not verify access in the other host.

Reconcile both outputs. Keep Model and Effort; use host-accepted Codex models and Claude aliases, never cross providers, mark Claude effort advisory, apply the token-efficiency preference below, and reassess on scope changes. Ask the user for shallow placement, membership, order, or scope ambiguity; never broaden inspection. The parent alone writes files, applies an accepted move, creates a branch, or switches branches.

## Model selection preference

Favor the supported model and effort expected to use fewer total tokens for a good, complete result, including reasoning, repeated context, retries, and rework. Apply this objective to both Codex and Claude. Preserve completeness, correctness, and required validation.

Use current official guidance or observed task results to compare efficiency. Model age, size, and price per token do not establish total token usage: neither older nor newer automatically means fewer tokens. When comparative evidence is unavailable, state the uncertainty and choose a reliable supported model without inventing an efficiency ranking. Honor explicit user choices and keep the existing Fable exclusion.

## Create or organize

Before creation, verify a clean Git worktree on `development`; allocate the global max-plus-one ID; preflight; create/switch the exact branch; apply an accepted move while clean; then run `create` and author. Ask before Git initialization. The branch must equal `LEAF/NNNN-SLUG` and be absent from local and tracked-remote refs. `create` stages `docs/template/` and changes only the new destination. Author title, assignee, status, goal, context, concrete todos, creation/change, actual validation, a first next step, decisions, phase scope, compact recommendations, and TODO entry; then run `validate` and `validate-todo`, confirm the template is unchanged, report the result, and stop unless asked to implement. When a task becomes Completed, update its semantic records, then run `complete ROOT TASK_PATH`; it atomically updates the TODO entry and Chronology.

For an unambiguous accepted sibling plan, run `validate-move ROOT PLAN.json`, then `apply-move ROOT PLAN.json`. Plans move only direct parent siblings into its one new child leaf, preserve listed order and every task's global ID, and stage TODO, Chronology, and Markdown inbound-reference updates before the transaction. Stop if any affected branch needs migration; task reorganization never authorizes Git-ref mutation.

## Select or switch

Use `resolve ROOT` to select exactly one `Current`, otherwise exactly one `Next`; it never infers from a branch. An explicit user choice may use `switch-preflight ROOT TASK_PATH` only after a clean tracked-and-untracked status, one existing local branch, and no other worktree checkout. Never stash, discard, commit, carry, force, or create a missing branch. After a successful authorized switch, update the selected TODO entry through the normal scoped record update.

## Boundaries

Explicit creation authorizes only creation and switching to the new branch from `development`; confirm the worktree/base and ask before Git initialization or a nonstandard switch. Every task requires its exact full-path branch. Do not stage, commit, push, merge, rebase, rename refs, or start implementation.
