# Shared contract for compliance checks. Source it, set CHECK_NAME,
# call exactly one of pass/fail/skip.
# shellcheck disable=SC2148
pass() { echo "PASS: $CHECK_NAME - $1"; exit 0; }
fail() { echo "FAIL: $CHECK_NAME - $1"; exit 1; }
skip() { echo "SKIP: $CHECK_NAME - $1"; exit 2; }
need() {
  if ! command -v "$1" >/dev/null 2>&1; then
    fail "required tool missing: $1"
  fi
}
