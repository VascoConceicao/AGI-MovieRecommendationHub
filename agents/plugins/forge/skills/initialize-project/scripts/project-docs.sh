#!/bin/sh
set -eu

usage() {
  echo "usage: $0 inspect <root> | validate <root>" >&2
  exit 64
}

fail() {
  echo "initialize-project: error code=$1${2:+ message=$2}" >&2
  exit 1
}

documents='README.md docs/project-spec.md docs/ai-context.md'

root_exists() {
  [ -d "$1" ] || fail missing-root "$1"
}

inspect() {
  root_exists "$1"
  for document in $documents; do
    if [ -f "$1/$document" ]; then
      printf 'document\t%s\tpresent\n' "$document"
    else
      printf 'document\t%s\tmissing\n' "$document"
    fi
  done
}

has_heading() {
  awk 'NF { found=1; exit ($0 ~ /^# [^[:space:]]/) ? 0 : 1 } END { if (!found) exit 1 }' "$1"
}

placeholders() {
  awk '
    /^```/ { fenced = !fenced; next }
    /\{\{TODO:[^}]+\}\}/ { print FNR ":" $0; next }
    !fenced && /<(Describe|List|Name|Document|Record) [^>]+>/ { print FNR ":" $0; next }
    !fenced && /<Project Name>/ { print FNR ":" $0; next }
    fenced && /^<[a-z]+-command>$/ { print FNR ":" $0 }
  ' "$1"
}

validate() {
  root=$1
  root_exists "$root"
  for document in $documents; do
    path=$root/$document
    [ -f "$path" ] || fail missing-document "$document"
    has_heading "$path" || fail missing-title "$document"
    markers=$(placeholders "$path")
    [ -z "$markers" ] || fail unresolved-placeholder "$document:$markers"
  done
  printf 'validation\tpassed\n'
}

[ "$#" -eq 2 ] || usage
case $1 in
  inspect) inspect "$2" ;;
  validate) validate "$2" ;;
  *) usage ;;
esac
