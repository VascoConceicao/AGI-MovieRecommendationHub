---
name: push
description: Review all non-ignored Git changes, divide them into the smallest coherent commits, commit them, and push the current branch. Use only when the user explicitly invokes $push or clearly asks to commit and push all current work. One commit is correct when the complete diff represents one cohesive change.
---

# Push Changes

Turn the current worktree into a clean, reviewable commit sequence and push the current branch. Explicit invocation authorizes normal staging, commits, and a normal push only; never force-push, rewrite history, bypass hooks, discard changes, create remotes, or expose sensitive data.
Resolve bundled helpers relative to this loaded skill’s directory, and pass the selected repository root explicitly. Installed resources may live in a cache; never derive or edit the project there.


## Inspect and validate

Follow repository startup; update the selected task's state before committing. Run these read-only checks from the repository root:

```sh
sh <loaded-skill-directory>/scripts/push-check.sh preflight <root>
sh <loaded-skill-directory>/scripts/push-check.sh status <root>
sh <loaded-skill-directory>/scripts/push-check.sh sensitive-paths <root>
```

`preflight` rejects detached HEAD and merge, rebase, or cherry-pick state, and reports the branch, configured upstream, and remotes; `status` includes tracked, staged, and non-ignored untracked work; `sensitive-paths` reports name-based candidates only. Inspect unstaged and staged diffs, relevant untracked-file content, and recent commit subjects yourself. Never stage ignored files.

Stop and ask if a remote is not unambiguous; a candidate looks sensitive (credentials, keys, personal data, environment files, or large/generated artifacts); or intentionally grouped staged work needs rearranging. Account for all safe non-ignored changes—do not discard or silently omit unrelated pre-existing work. The helper cannot classify content or select a remote; review remains required.

Run relevant existing checks when practical. Diagnose failures and fix only corrections clearly within the committed work; otherwise stop. Never use `--no-verify`.

## Commit deliberately

Group by purpose and dependency, keeping implementation with its tests/configuration, manifests with lockfiles, and renames with related edits. Separate independent work only when each commit remains understandable; use one when splitting adds noise or leaves an incomplete intermediate state. Do not rewrite files merely to split them. Briefly summarize groups, then continue unless a safety condition requires input.

For each group, stage only intended paths or hunks, inspect `git diff --cached`, commit an imperative history-consistent subject, and record its hash and subject. Do not amend without explicit user request. Afterward, either account for every non-ignored remaining change in a coherent commit or stop and explain why it is unsafe.

## Push and report

Choose the remote by judgment, then validate it with `remote <root> <remote>`. Fetch only when practical and authorized by the repository workflow; the helper never fetches or handles credentials. Run `upstream <root> <remote> <branch>` to report ahead/behind from the locally available tracking ref. Stop when behind or diverged—never pull, merge, rebase, or force-push automatically.

With no upstream, use `git push -u <remote> <branch>`; otherwise use normal `git push`. If no worktree changes but commits are unpushed, push them; if neither exists, report cleanly. After a successful push, run `post-push <root> <remote> <branch>` to verify branch, configured upstream, a clean worktree, and local tracking-ref synchronization.

Report the branch/remote, new commits in order, validation outcomes, final status, and remaining or rejected work.
