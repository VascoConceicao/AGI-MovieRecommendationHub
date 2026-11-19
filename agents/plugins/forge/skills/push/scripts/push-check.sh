#!/bin/sh
set -eu

usage() {
  echo "usage: $0 preflight <root> | status <root> | remote <root> <remote> | sensitive-paths <root> | upstream <root> <remote> <branch> | post-push <root> <remote> <branch>" >&2
  exit 64
}

fail() {
  echo "push: error code=$1${2:+ message=$2}" >&2
  exit 1
}

repository() {
  root=$1
  [ -d "$root" ] || fail missing-root "$root"
  git -C "$root" rev-parse --is-inside-work-tree >/dev/null 2>&1 || fail not-a-git-worktree "$root"
}

branch() {
  git -C "$1" symbolic-ref --quiet --short HEAD || fail detached-head
}

operation() {
  root=$1
  git_dir=$(git -C "$root" rev-parse --git-dir)
  case $git_dir in
    /*) ;;
    *) git_dir=$root/$git_dir ;;
  esac
  for marker in MERGE_HEAD REBASE_HEAD CHERRY_PICK_HEAD REVERT_HEAD; do
    [ ! -e "$git_dir/$marker" ] || fail git-operation "$marker"
  done
  [ ! -d "$git_dir/rebase-apply" ] || fail git-operation rebase-apply
  [ ! -d "$git_dir/rebase-merge" ] || fail git-operation rebase-merge
  [ ! -d "$git_dir/sequencer" ] || fail git-operation sequencer
}

preflight() {
  root=$1
  repository "$root"
  operation "$root"
  current_branch=$(branch "$root")
  printf 'branch\t%s\n' "$current_branch"
  configured_upstream=$(git -C "$root" for-each-ref --format='%(upstream:short)' "refs/heads/$current_branch")
  printf 'upstream\t%s\n' "${configured_upstream:-none}"
  git -C "$root" remote | while IFS= read -r remote_name; do
    [ -n "$remote_name" ] || continue
    printf 'remote\t%s\n' "$remote_name"
  done
}

status() {
  repository "$1"
  git -C "$1" status --short --branch --untracked-files=all
}

remote() {
  root=$1
  remote_name=$2
  repository "$root"
  git -C "$root" remote get-url "$remote_name" >/dev/null 2>&1 || fail unknown-remote "$remote_name"
  printf 'remote\t%s\n' "$remote_name"
}

candidate_paths() {
  root=$1
  {
    git -C "$root" diff --name-only
    git -C "$root" diff --cached --name-only
    git -C "$root" ls-files --others --exclude-standard
  } | sort -u
}

sensitive_paths() {
  root=$1
  repository "$root"
  candidate_paths "$root" | while IFS= read -r path; do
    case $path in
      .env|.env.*|*.env|*/.env|*/.env.*|*.pem|*.key|*.p12|*.pfx|*/id_rsa|*/id_ed25519|*/id_ecdsa|id_rsa|id_ed25519|id_ecdsa|credentials*|*/credentials*|secrets*|*/secrets*|*token*|*password*)
        printf 'candidate-sensitive-path\t%s\n' "$path"
        ;;
    esac
  done
}

upstream() {
  root=$1
  remote_name=$2
  requested_branch=$3
  repository "$root"
  remote "$root" "$remote_name" >/dev/null
  [ "$(branch "$root")" = "$requested_branch" ] || fail branch-mismatch "expected=$requested_branch"
  tracking_ref="refs/remotes/$remote_name/$requested_branch"
  git -C "$root" rev-parse --verify --quiet "$tracking_ref" >/dev/null || fail missing-remote-tracking-ref "$tracking_ref"
  set -- $(git -C "$root" rev-list --left-right --count "$requested_branch...$tracking_ref")
  printf 'upstream-state\tremote=%s\tbranch=%s\tahead=%s\tbehind=%s\n' "$remote_name" "$requested_branch" "$1" "$2"
}

post_push() {
  root=$1
  remote_name=$2
  requested_branch=$3
  repository "$root"
  [ "$(branch "$root")" = "$requested_branch" ] || fail branch-mismatch "expected=$requested_branch"
  configured_upstream=$(git -C "$root" for-each-ref --format='%(upstream:short)' "refs/heads/$requested_branch")
  [ "$configured_upstream" = "$remote_name/$requested_branch" ] || fail upstream-mismatch "expected=$remote_name/$requested_branch actual=${configured_upstream:-none}"
  [ -z "$(git -C "$root" status --porcelain --untracked-files=all)" ] || fail remaining-worktree-changes
  tracking_ref="refs/remotes/$remote_name/$requested_branch"
  git -C "$root" rev-parse --verify --quiet "$tracking_ref" >/dev/null || fail missing-remote-tracking-ref "$tracking_ref"
  set -- $(git -C "$root" rev-list --left-right --count "$requested_branch...$tracking_ref")
  [ "$1" = 0 ] && [ "$2" = 0 ] || fail post-push-not-synchronized "ahead=$1 behind=$2"
  printf 'post-push\tbranch=%s\tupstream=%s/%s\tworktree=clean\n' "$requested_branch" "$remote_name" "$requested_branch"
}

[ "$#" -ge 1 ] || usage
command=$1
shift
case $command in
  preflight) [ "$#" -eq 1 ] || usage; preflight "$1" ;;
  status) [ "$#" -eq 1 ] || usage; status "$1" ;;
  sensitive-paths) [ "$#" -eq 1 ] || usage; sensitive_paths "$1" ;;
  remote) [ "$#" -eq 2 ] || usage; remote "$@" ;;
  upstream) [ "$#" -eq 3 ] || usage; upstream "$@" ;;
  post-push) [ "$#" -eq 3 ] || usage; post_push "$@" ;;
  *) usage ;;
esac
