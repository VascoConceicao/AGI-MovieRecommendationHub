# Tasks

This directory is the task-tracking authority.

Real tasks live in semantic leaf folders named:

```text
docs/tasks/<category>[/<subcategory>...]/<task-id-and-name>/
├── state.md
├── decisions.md
└── phases/
```

The reusable shape is `docs/template/`. IDs are globally unique and allocated as the recursive maximum plus one; moves preserve IDs. A task branch exactly mirrors its path relative to `docs/tasks/`.

`docs/TODO.md` selects current/next work; its nested lists mirror category directories and `create-task` owns its grammar and validation:

```sh
sh agents/plugins/forge/skills/create-task/scripts/task-helper.sh resolve .
```

Never select from a branch or duplicate TODO grammar.

The final, append-only `## Chronology` lists every Completed task once as an ordered full-path link; order is authoritative completion order, with no dates or incomplete tasks.

- `state.md` tracks the task's current status, todo list, changes, validation, and next steps.
- `decisions.md` records decisions that affect the task.
- `phases/` contains ordered Markdown files for phase-specific work.

## Creating a Task

In Codex use `$create-task`; in Claude Code use `/forge:create-task`. It owns semantic placement, global numbering, path-qualified branch validation, TODO and Chronology updates/validation, and safe explicit-switch preflight.

## Implementing Phases

In Codex invoke `$implement-phase`; in Claude Code invoke `/forge:implement-phase`. It asks whether to use a native subagent with the recommended model and effort or continue in the current conversation, accepts a supported alternative model, defaults to sequential review gates, and never commits or pushes.

## Conventions

- Do not store the current task in this README.
- Keep task names lowercase and hyphenated.
- Keep category segments lowercase and hyphenated; task hierarchy depth is unbounded.
- Every task's `state.md` must include a `Todo` section with Markdown checkboxes.
- Every phase must compactly record one Codex model and effort plus one Claude Code model and advisory effort.
- Discover current native sub-agent availability before writing recommendations; never recommend or launch Claude `fable`.
- Treat both model recommendations as advisory and reassess them when phase scope changes.
- Update `state.md`, `decisions.md`, and relevant phase files automatically when their information changes.
