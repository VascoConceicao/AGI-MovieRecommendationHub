# AI Bootstrap

## Startup Order

1. Read `AGENTS.md`, this file, and `docs/ai-context.md` once; reuse unchanged context. General questions need no repo inspection.
2. Before edits, check branch and worktree status.
3. For tracked work, run `sh agents/plugins/forge/skills/create-task/scripts/task-helper.sh resolve .`; read the task state, decisions, and relevant phase. Never select a task from the branch alone.
4. Read setup, product specs, task workflow, and older records only when relevant. Search scoped paths with `rg`.

## Task Folder Workflow

- Follow the concrete user request. Standalone work needs no task; create/switch tasks only when requested, using `create-task`. Resolve task/branch conflicts before dependent work.
- Keep task state, decisions, and phases current. Put implementation details and task-specific instructions there, not in bootstrap.

## Operating Rules

- Git is read-only unless explicitly authorized. Preserve existing work; never overwrite conflicting changes or force a switch.
- Run relevant checks. Add tests/coverage only when requested. Keep secrets, environments, caches, and generated artifacts ignored.
- Write simply and briefly. Shortened grammar is fine when meaning and accuracy stay clear.
- Resolve installed-skill helpers from their loaded location and pass the target repo explicitly.
