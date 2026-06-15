#!/bin/bash
#
# Tests for src/logging.sh unified log-level filtering.
# Run: bash tests/test_logging.sh
#
set -o pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../src" && pwd)"
PASS=0
FAIL=0

assert_contains() {
  local label="$1" output="$2" expected="$3"
  if echo "$output" | grep -q "$expected"; then
    ((PASS++))
  else
    echo "FAIL [$label]: expected output to contain '$expected'"
    echo "  got: $output"
    ((FAIL++))
  fi
}

assert_not_contains() {
  local label="$1" output="$2" unexpected="$3"
  if echo "$output" | grep -q "$unexpected"; then
    echo "FAIL [$label]: expected output NOT to contain '$unexpected'"
    echo "  got: $output"
    ((FAIL++))
  else
    ((PASS++))
  fi
}

assert_empty() {
  local label="$1" output="$2"
  if [[ -z "$output" ]]; then
    ((PASS++))
  else
    echo "FAIL [$label]: expected empty output"
    echo "  got: $output"
    ((FAIL++))
  fi
}

# Helper: run all four log functions in a subshell, capture stderr and stdout separately.
# Sets: captured_stderr, captured_stdout
run_log_functions() {
  local env_setup="$1"
  local tmpout tmperr
  tmpout=$(mktemp)
  tmperr=$(mktemp)
  bash -c "${env_setup} LOG_NAME=Test; source '${SCRIPT_DIR}/logging.sh'; log_debug 'D'; log 'I'; log_warn 'W'; log_error 'E'" \
    >"$tmpout" 2>"$tmperr" || true
  captured_stdout=$(cat "$tmpout")
  captured_stderr=$(cat "$tmperr")
  rm -f "$tmpout" "$tmperr"
}

echo "=== Testing src/logging.sh ==="

# ── Test 1: Default level (info) ───────────────────────────────────────────
run_log_functions "unset CONTAINER_VERBOSE; unset CONTAINER_LOG_LEVEL;"
assert_not_contains "default: no debug"  "$captured_stderr" "\\[.*debug.*\\]"
assert_contains     "default: has info"  "$captured_stderr" "info"
assert_contains     "default: has warn"  "$captured_stderr" "warn"
assert_contains     "default: has error" "$captured_stderr" "error"
assert_empty        "default: stdout empty" "$captured_stdout"

# ── Test 2: debug level ───────────────────────────────────────────────────
run_log_functions "unset CONTAINER_VERBOSE; export CONTAINER_LOG_LEVEL=debug;"
assert_contains "debug: has debug" "$captured_stderr" "debug"
assert_contains "debug: has info"  "$captured_stderr" "info"
assert_contains "debug: has warn"  "$captured_stderr" "warn"
assert_contains "debug: has error" "$captured_stderr" "error"
assert_empty    "debug: stdout empty" "$captured_stdout"

# ── Test 3: warn level ────────────────────────────────────────────────────
run_log_functions "unset CONTAINER_VERBOSE; export CONTAINER_LOG_LEVEL=warn;"
assert_not_contains "warn: no debug" "$captured_stderr" "debug"
assert_not_contains "warn: no info"  "$captured_stderr" "info"
assert_contains     "warn: has warn"  "$captured_stderr" "warn"
assert_contains     "warn: has error" "$captured_stderr" "error"

# ── Test 4: error level ───────────────────────────────────────────────────
run_log_functions "unset CONTAINER_VERBOSE; export CONTAINER_LOG_LEVEL=error;"
assert_not_contains "error: no debug" "$captured_stderr" "debug"
assert_not_contains "error: no info"  "$captured_stderr" "info"
assert_not_contains "error: no warn"  "$captured_stderr" "warn"
assert_contains     "error: has error" "$captured_stderr" "error"

# ── Test 5: quiet level ───────────────────────────────────────────────────
run_log_functions "unset CONTAINER_VERBOSE; export CONTAINER_LOG_LEVEL=quiet;"
assert_empty "quiet: stderr empty" "$captured_stderr"
assert_empty "quiet: stdout empty" "$captured_stdout"

# ── Test 6: CONTAINER_VERBOSE backward compat ─────────────────────────────
run_log_functions "export CONTAINER_VERBOSE=true; unset CONTAINER_LOG_LEVEL;"
assert_contains "verbose compat: has debug" "$captured_stderr" "debug"
assert_contains "verbose compat: has info"  "$captured_stderr" "info"

# ── Test 7: CONTAINER_LOG_LEVEL takes precedence over CONTAINER_VERBOSE ───
run_log_functions "export CONTAINER_VERBOSE=true; export CONTAINER_LOG_LEVEL=error;"
assert_not_contains "precedence: no debug" "$captured_stderr" "debug"
assert_not_contains "precedence: no info"  "$captured_stderr" "info"
assert_contains     "precedence: has error" "$captured_stderr" "error"

# ── Test 8: Output format matches expected pattern ────────────────────────
run_log_functions "unset CONTAINER_VERBOSE; export CONTAINER_LOG_LEVEL=debug;"
assert_contains "format: LOG_NAME prefix" "$captured_stderr" "^Test |"
assert_contains "format: timestamp"       "$captured_stderr" "[0-9]\{4\}-[0-9]\{2\}-[0-9]\{2\} [0-9]\{2\}:[0-9]\{2\}:[0-9]\{2\}"

# ── Test 9: Unknown level defaults to info ────────────────────────────────
run_log_functions "unset CONTAINER_VERBOSE; export CONTAINER_LOG_LEVEL=bogus;"
assert_not_contains "unknown: no debug" "$captured_stderr" "debug"
assert_contains     "unknown: has info"  "$captured_stderr" "info"

# ── Summary ────────────────────────────────────────────────────────────────
echo ""
echo "Results: ${PASS} passed, ${FAIL} failed"
if [[ $FAIL -gt 0 ]]; then
  exit 1
fi
echo "All tests passed."
