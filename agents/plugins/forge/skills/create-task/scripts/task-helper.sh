#!/bin/sh
set -eu

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
engine="$script_dir/task_engine.py"

usage() {
  echo "usage: $0 leaves TASKS_DIR | next-id TASKS_DIR | resolve ROOT | validate-todo ROOT | complete ROOT TASK_PATH | preflight ROOT LEAF NNNN-SLUG PHASE BRANCH [PLAN.json] | create ROOT LEAF NNNN-SLUG PHASE BRANCH | validate ROOT LEAF NNNN-SLUG PHASE BRANCH | switch-preflight ROOT TASK_PATH | validate-move ROOT PLAN.json | apply-move ROOT PLAN.json" >&2
  exit 64
}

fail() { echo "create-task: $*" >&2; exit 1; }

run_engine() { python3 "$engine" "$@"; }

valid_phase() { printf '%s\n' "$1" | grep -Eq '^[0-9][0-9]-[a-z0-9]+(-[a-z0-9]+)*\.md$'; }

branch_unused() {
  root=$1 branch=$2
  git -C "$root" check-ref-format --branch "$branch" >/dev/null 2>&1 || fail "invalid branch path: $branch"
  if git -C "$root" for-each-ref --format='%(refname:short)' refs/heads refs/remotes | awk -v branch="$branch" '
    function conflict(value) { return value == branch || index(value, branch "/") == 1 || index(branch, value "/") == 1 }
    conflict($0) { found=1 }
    index($0, "/") { remote=substr($0, index($0, "/") + 1); if (conflict(remote)) found=1 }
    END { exit !found }
  '; then
    fail "branch or its ref namespace already exists locally or on a tracked remote: $branch"
  fi
}

git_creation_preflight() {
  root=$1
  [ "$(git -C "$root" rev-parse --is-inside-work-tree 2>/dev/null || true)" = true ] || fail "not a Git worktree; ask before Git initialization"
  [ "$(git -C "$root" branch --show-current)" = development ] || fail "new task creation must start on development"
  [ -z "$(git -C "$root" status --short)" ] || fail "worktree is not clean; ask the user how to handle every change"
}

preflight() {
  root=$1 leaf=$2 name=$3 phase=$4 branch=$5 plan=${6:-}
  valid_phase "$phase" || fail "invalid phase name: $phase"
  expected="$leaf/$name"
  git_creation_preflight "$root"
  if [ -n "$plan" ]; then
    run_engine preflight-move-path "$root" "$leaf" "$name" "$branch" "$plan" >/dev/null
  else
    run_engine preflight-path "$root/docs/tasks" "$leaf" "$name" "$branch" >/dev/null
  fi
  [ -d "$root/docs/template" ] || fail "missing task template"
  [ ! -L "$root/docs/template" ] || fail "task template may not be a symlink"
  for path in state.md decisions.md phases phases/README.md phases/phase.md; do
    [ -e "$root/docs/template/$path" ] || fail "task template is missing: $path"
  done
  branch_unused "$root" "$branch"
  printf '%s\n' "create-task: ready: docs/tasks/$expected"
}

create() {
  root=$1 leaf=$2 name=$3 phase=$4 branch=$5
  valid_phase "$phase" || fail "invalid phase name: $phase"
  run_engine preflight-path "$root/docs/tasks" "$leaf" "$name" "$branch" >/dev/null
  [ "$(git -C "$root" branch --show-current)" = "$branch" ] || fail "create requires the exact checked-out task branch: $branch"
  destination="$root/docs/tasks/$leaf/$name"
  parent=$(dirname "$destination")
  stage=$(mktemp -d "$root/docs/tasks/.create-task-stage.XXXXXX") || fail "cannot stage task"
  trap 'rm -rf "$stage"' EXIT HUP INT TERM
  cp -R "$root/docs/template" "$stage/task"
  rm "$stage/task/phases/README.md"
  mv "$stage/task/phases/phase.md" "$stage/task/phases/$phase"
  mkdir -p "$parent"
  mv "$stage/task" "$destination"
  trap - EXIT HUP INT TERM
  rmdir "$stage"
  printf '%s\n' "create-task: created: docs/tasks/$leaf/$name"
}

validate() {
  root=$1 leaf=$2 name=$3 phase=$4 branch=$5
  valid_phase "$phase" || fail "invalid phase name: $phase"
  expected="$leaf/$name"
  run_engine task-path "$leaf" "$name" "$branch" >/dev/null
  destination="$root/docs/tasks/$expected"
  [ -f "$destination/state.md" ] || fail "missing state.md"
  [ -f "$destination/decisions.md" ] || fail "missing decisions.md"
  [ -f "$destination/phases/$phase" ] || fail "missing initial phase"
  [ ! -e "$destination/phases/README.md" ] || fail "unexpected phases/README.md"
  [ ! -e "$destination/phases/phase.md" ] || fail "unexpected phases/phase.md"
  [ "$(find "$destination/phases" -type f -name '*.md' | wc -l | tr -d ' ')" -eq 1 ] || fail "expected exactly one phase"
  if grep -Eq '<[^>]+>' "$destination/state.md" "$destination/decisions.md" "$destination/phases/$phase"; then
    fail "unreplaced angle-bracket placeholder"
  fi
  awk '
    /^## Recommended Model$/ { in_block=1; next }
    in_block && /^## / { exit }
    in_block && /^### Codex$/ { provider="codex"; seen[provider]=1; next }
    in_block && /^### Claude Code$/ { provider="claude"; seen[provider]=1; next }
    in_block && /^- Model: / { model[provider]++; if (provider == "claude" && /fable/) bad=1; next }
    in_block && /^- Effort: / { effort[provider]++; next }
    END { exit !(seen["codex"] && seen["claude"] && model["codex"] == 1 && effort["codex"] == 1 && model["claude"] == 1 && effort["claude"] == 1 && !bad) }
  ' "$destination/phases/$phase" || fail "invalid compact recommendations"
  printf '%s\n' "create-task: validated: docs/tasks/$expected"
}

switch_preflight() {
  root=$1 task=$2
  run_engine branch-path "$task" >/dev/null
  run_engine validate-layout "$root" >/dev/null
  [ -d "$root/docs/tasks/$task" ] || fail "selected task is missing: $task"
  git -C "$root" diff --quiet && git -C "$root" diff --cached --quiet && [ -z "$(git -C "$root" status --short)" ] || fail "worktree is not clean; ask the user how to handle every change"
  current=$(CDPATH= cd -- "$root" && pwd -P)
  if git -C "$root" worktree list --porcelain | awk -v branch="refs/heads/$task" -v current="$current" '
    $1 == "worktree" { worktree=$2 }
    $1 == "branch" && $2 == branch && worktree != current { found=1 }
    END { exit !found }
  '; then
    fail "target branch is checked out in another worktree: $task"
  fi
  git -C "$root" show-ref --verify --quiet "refs/heads/$task" || fail "target branch is missing: $task"
  printf '%s\n' "create-task: switch-ready: $task"
}

[ "$#" -ge 1 ] || usage
action=$1; shift
case "$action" in
  leaves) [ "$#" -eq 1 ] || usage; run_engine leaves "$1" ;;
  next-id) [ "$#" -eq 1 ] || usage; run_engine next-id "$1" ;;
  resolve) [ "$#" -eq 1 ] || usage; run_engine resolve "$1" ;;
  validate-todo) [ "$#" -eq 1 ] || usage; run_engine validate-todo "$1" ;;
  complete) [ "$#" -eq 2 ] || usage; python3 "$script_dir/complete_task.py" "$1" "$2" ;;
  preflight) { [ "$#" -eq 5 ] || [ "$#" -eq 6 ]; } || usage; preflight "$@" ;;
  create) [ "$#" -eq 5 ] || usage; create "$@" ;;
  validate) [ "$#" -eq 5 ] || usage; validate "$@" ;;
  switch-preflight) [ "$#" -eq 2 ] || usage; switch_preflight "$@" ;;
  validate-move) [ "$#" -eq 2 ] || usage; run_engine validate-move "$1" "$2" ;;
  apply-move) [ "$#" -eq 2 ] || usage; run_engine validate-move "$1" "$2" >/dev/null; python3 "$script_dir/apply_move.py" "$1" "$2" ;;
  *) usage ;;
esac
