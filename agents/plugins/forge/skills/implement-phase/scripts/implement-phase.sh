#!/bin/sh
set -eu

usage() {
  echo "usage: $0 task ROOT | phases TASK_DIR | resolve ROOT [PHASE_NAME ...]" >&2
  exit 64
}

fail() {
  echo "implement-phase: error code=$1${2:+ message=$2}" >&2
  exit 1
}

valid_phase_name() {
  printf '%s\n' "$1" | grep -Eq '^[0-9][0-9]-[a-z0-9]+(-[a-z0-9]+)*\.md$'
}

task_name() {
  root=$1
  script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
  helper=$script_dir/../../create-task/scripts/task-helper.sh
  [ -x "$helper" ] || fail missing-task-resolver "$helper"
  if ! output=$(sh "$helper" resolve "$root"); then
    fail todo-resolution "${output:-create-task resolver failed}"
  fi
  resolved=$(printf '%s\n' "$output" | python3 -c '
import json, sys
try:
    value = json.load(sys.stdin)
    task = value["task"]
    expected = value["expected_branch"]
    assert value.get("ok") is True and isinstance(task, str)
    assert expected == task
except (AssertionError, KeyError, TypeError, json.JSONDecodeError):
    raise SystemExit(1)
print(task)
' ) || fail invalid-task-resolver-output "$output"
  task=$(printf '%s\n' "$resolved" | sed -n '1p')
  [ -d "$root/docs/tasks/$task" ] || fail missing-selected-task "$task"
  branch=$(git -C "$root" branch --show-current 2>/dev/null || true)
  [ "$branch" = "$task" ] || \
    fail branch-disagreement "selected=$task expected=$task branch=${branch:-detached}"
  printf '%s\n' "$task"
}

status() {
  awk '
    /^## Status$/ { found=1; next }
    found && /^## / { exit }
    found && NF { sub(/[[:space:]]+$/, ""); sub(/\.$/, ""); print; seen=1; exit }
    END { if (!seen) exit 1 }
  ' "$1" || fail missing-status "$1"
}

recommendation() {
  phase=$1
  provider=$2
  awk -v provider="$provider" '
    /^## Recommended Model$/ { block=1; next }
    block && /^## / { exit }
    block && /^### / { active=substr($0, 5); if (active == provider) sections++; next }
    block && active == provider && /^- Model: `/ {
      value=$0; sub(/^- Model: `/, "", value); sub(/`.*/, "", value); model=value; models++
    }
    block && active == provider && /^- Effort: `/ {
      value=$0; sub(/^- Effort: `/, "", value); sub(/`.*/, "", value); effort=value; efforts++
    }
    END { if (block && sections == 1 && models == 1 && efforts == 1 && model != "" && effort != "") print model "\t" effort; else exit 1 }
  ' "$phase" || fail incomplete-recommendation "$phase provider=$provider"
}

phase_record() {
  phase=$1
  name=${phase##*/}
  valid_phase_name "$name" || fail invalid-phase-name "$name"
  state=$(status "$phase")
  codex=$(recommendation "$phase" Codex)
  claude=$(recommendation "$phase" 'Claude Code')
  claude_model=$(printf '%s\n' "$claude" | cut -f1)
  [ "$claude_model" != fable ] || fail forbidden-model "$phase provider=Claude-Code model=fable"
  printf '%s\t%s\t%s\t%s\n' "$name" "$state" "$codex" "$claude"
}

phases() {
  task=$1
  [ -d "$task/phases" ] || fail missing-phases-directory "$task/phases"
  found=false
  for phase in "$task/phases"/[0-9][0-9]-*.md; do
    [ -f "$phase" ] || continue
    found=true
    phase_record "$phase"
  done
  [ "$found" = true ] || fail no-phases "$task/phases"
}

resolve() {
  root=$1
  shift
  name=$(task_name "$root")
  task=$root/docs/tasks/$name
  selected=
  if [ "$#" -gt 0 ]; then
    for requested in "$@"; do
      requested=${requested##*/}
      valid_phase_name "$requested" || fail invalid-phase-name "$requested"
      [ -f "$task/phases/$requested" ] || fail unknown-phase "$requested"
      selected="${selected:+$selected }$requested"
    done
  else
    for phase in "$task/phases"/[0-9][0-9]-*.md; do
      [ -f "$phase" ] || continue
      current=$(status "$phase")
      [ "$current" = Completed ] && continue
      selected="${selected:+$selected }${phase##*/}"
    done
  fi
  [ -n "$selected" ] || fail no-incomplete-phases "$name"
  emitted=false
  for phase in $selected; do
    current=$(status "$task/phases/$phase")
    [ "$current" = Completed ] && continue
    phase_record "$task/phases/$phase"
    emitted=true
  done
  [ "$emitted" = true ] || fail no-incomplete-phases "$name"
}

[ "$#" -ge 1 ] || usage
command=$1
shift
case $command in
  task) [ "$#" -eq 1 ] || usage; task_name "$1" ;;
  phases) [ "$#" -eq 1 ] || usage; phases "$1" ;;
  resolve) [ "$#" -ge 1 ] || usage; resolve "$@" ;;
  *) usage ;;
esac
