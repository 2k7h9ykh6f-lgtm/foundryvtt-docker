#!/bin/bash

# test_logging.sh — Verify unified log level behavior across logging.sh
#
# Runs 8 test scenarios covering:
#   1. Default (info) level
#   2. Debug level via FOUNDRY_LOG_LEVEL
#   3. Warn level (quiet mode)
#   4. Error level
#   5. Backward compat: CONTAINER_VERBOSE → debug
#   6. FOUNDRY_LOG_LEVEL overrides CONTAINER_VERBOSE
#   7. Case insensitivity
#   8. log() is alias for log_info()
#
# Usage: bash tests/test_logging.sh

set -o pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
LOGGING_SH="${REPO_ROOT}/src/logging.sh"

PASS_COUNT=0
FAIL_COUNT=0

# ── Helpers ──────────────────────────────────────────────────────────────────

# run_logging_test <description> <env_vars> <expected_present> <expected_absent>
#
# Sources logging.sh in a subshell with the given environment, calls all four
# log functions, then checks that expected level tags are present/absent.
run_logging_test() {
  local description="$1"
  local env_vars="$2"
  local expected_present="$3"  # space-separated list of level tags that MUST appear
  local expected_absent="$4"   # space-separated list of level tags that MUST NOT appear

  # Run in a subshell so environment changes don't leak.
  # Capture stdout from all four log function calls.
  local output
  output=$(
    eval "${env_vars}"
    export LOG_NAME="Test"
    # shellcheck source=src/logging.sh
    source "${LOGGING_SH}"
    log_debug "debug-test-message"
    log_info  "info-test-message"
    log_warn  "warn-test-message"
    log_error "error-test-message"
  )

  # Strip ANSI color codes for level-tag matching
  local stripped
  stripped=$(echo "${output}" | sed $'s/\e\\[[0-9;]*m//g')

  local pass=true
  local details=""

  # Check expected-present levels
  for tag in ${expected_present}; do
    if ! echo "${stripped}" | grep -q "\[${tag}\]"; then
      pass=false
      details="${details}\n  MISSING expected [${tag}]"
    fi
  done

  # Check expected-absent levels
  for tag in ${expected_absent}; do
    if echo "${stripped}" | grep -q "\[${tag}\]"; then
      pass=false
      details="${details}\n  UNEXPECTED [${tag}] found"
    fi
  done

  # Verify message content for present levels
  for msg in debug-test-message info-test-message warn-test-message error-test-message; do
    local level_tag
    case "${msg}" in
      debug-*) level_tag="debug" ;;
      info-*)  level_tag="info"  ;;
      warn-*)  level_tag="warn"  ;;
      error-*) level_tag="error" ;;
    esac
    if echo "${expected_present}" | grep -q "${level_tag}"; then
      if ! echo "${stripped}" | grep -q "${msg}"; then
        pass=false
        details="${details}\n  MISSING message '${msg}'"
      fi
    else
      if echo "${stripped}" | grep -q "${msg}"; then
        pass=false
        details="${details}\n  UNEXPECTED message '${msg}'"
      fi
    fi
  done

  if [[ "${pass}" == "true" ]]; then
    PASS_COUNT=$((PASS_COUNT + 1))
    echo "  PASS: ${description}"
  else
    FAIL_COUNT=$((FAIL_COUNT + 1))
    echo "  FAIL: ${description}"
    echo -e "  Output was:"
    echo "${output}" | sed 's/^/    /'
    echo -e "${details}"
  fi
}

# ── Test Cases ───────────────────────────────────────────────────────────────

echo "=== Shell Logging Tests (logging.sh) ==="
echo ""

# Test 1: Default level (info) — no env vars set
run_logging_test \
  "Default level (info): info+warn+error visible, debug hidden" \
  "unset FOUNDRY_LOG_LEVEL; unset CONTAINER_VERBOSE;" \
  "info warn error" \
  "debug"

# Test 2: FOUNDRY_LOG_LEVEL=debug — all levels visible
run_logging_test \
  "FOUNDRY_LOG_LEVEL=debug: all levels visible" \
  "export FOUNDRY_LOG_LEVEL=debug;" \
  "debug info warn error" \
  ""

# Test 3: FOUNDRY_LOG_LEVEL=warn (quiet mode) — only warn+error visible
run_logging_test \
  "FOUNDRY_LOG_LEVEL=warn (quiet): warn+error visible, info+debug hidden" \
  "export FOUNDRY_LOG_LEVEL=warn;" \
  "warn error" \
  "debug info"

# Test 4: FOUNDRY_LOG_LEVEL=error — only error visible
run_logging_test \
  "FOUNDRY_LOG_LEVEL=error: only error visible" \
  "export FOUNDRY_LOG_LEVEL=error;" \
  "error" \
  "debug info warn"

# Test 5: Backward compat — CONTAINER_VERBOSE implies debug
run_logging_test \
  "CONTAINER_VERBOSE set (backward compat): debug level enabled" \
  "unset FOUNDRY_LOG_LEVEL; export CONTAINER_VERBOSE=true;" \
  "debug info warn error" \
  ""

# Test 6: FOUNDRY_LOG_LEVEL overrides CONTAINER_VERBOSE
run_logging_test \
  "FOUNDRY_LOG_LEVEL=warn overrides CONTAINER_VERBOSE" \
  "export FOUNDRY_LOG_LEVEL=warn; export CONTAINER_VERBOSE=true;" \
  "warn error" \
  "debug info"

# Test 7: Case insensitivity — FOUNDRY_LOG_LEVEL=DEBUG works
run_logging_test \
  "Case insensitivity: FOUNDRY_LOG_LEVEL=DEBUG (uppercase)" \
  "export FOUNDRY_LOG_LEVEL=DEBUG;" \
  "debug info warn error" \
  ""

# Test 8: log() is alias for log_info()
echo -n "  "
output_8=$(
  unset FOUNDRY_LOG_LEVEL
  unset CONTAINER_VERBOSE
  export LOG_NAME="Test"
  # shellcheck source=src/logging.sh
  source "${LOGGING_SH}"
  log "alias-test-message"
)
stripped_8=$(echo "${output_8}" | sed $'s/\e\\[[0-9;]*m//g')
if echo "${stripped_8}" | grep -q '\[info\]' && echo "${stripped_8}" | grep -q 'alias-test-message'; then
  PASS_COUNT=$((PASS_COUNT + 1))
  echo "PASS: log() outputs as info level (alias for log_info)"
else
  FAIL_COUNT=$((FAIL_COUNT + 1))
  echo "FAIL: log() should output as info level"
  echo "  Output: ${output_8}"
fi

# ── Test: Entrypoint log level resolution ────────────────────────────────────

echo ""
echo "=== Entrypoint Log Level Bridge Tests ==="
echo ""

# Test the _ts_log_level resolution logic extracted from entrypoint.sh
test_ts_log_level() {
  local description="$1"
  local env_setup="$2"
  local expected_level="$3"

  local result
  result=$(
    eval "${env_setup}"
    # Replicate the resolution logic from entrypoint.sh
    _ts_log_level="${FOUNDRY_LOG_LEVEL:-}"
    if [[ -z "${_ts_log_level}" && "${CONTAINER_VERBOSE:-}" ]]; then
      _ts_log_level="debug"
    fi
    _ts_log_level="${_ts_log_level:-info}"
    echo "${_ts_log_level}"
  )

  if [[ "${result}" == "${expected_level}" ]]; then
    PASS_COUNT=$((PASS_COUNT + 1))
    echo "  PASS: ${description} → ${result}"
  else
    FAIL_COUNT=$((FAIL_COUNT + 1))
    echo "  FAIL: ${description} → got '${result}', expected '${expected_level}'"
  fi
}

echo -n ""
test_ts_log_level \
  "No env vars → info" \
  "unset FOUNDRY_LOG_LEVEL; unset CONTAINER_VERBOSE;" \
  "info"

test_ts_log_level \
  "FOUNDRY_LOG_LEVEL=debug → debug" \
  "export FOUNDRY_LOG_LEVEL=debug;" \
  "debug"

test_ts_log_level \
  "FOUNDRY_LOG_LEVEL=warn → warn" \
  "export FOUNDRY_LOG_LEVEL=warn;" \
  "warn"

test_ts_log_level \
  "FOUNDRY_LOG_LEVEL=error → error" \
  "export FOUNDRY_LOG_LEVEL=error;" \
  "error"

test_ts_log_level \
  "CONTAINER_VERBOSE=true → debug (backward compat)" \
  "unset FOUNDRY_LOG_LEVEL; export CONTAINER_VERBOSE=true;" \
  "debug"

test_ts_log_level \
  "FOUNDRY_LOG_LEVEL=warn + CONTAINER_VERBOSE=true → warn (explicit wins)" \
  "export FOUNDRY_LOG_LEVEL=warn; export CONTAINER_VERBOSE=true;" \
  "warn"

# ── Test: Log format consistency ──────────────────────────────────────────────

echo ""
echo "=== Log Format Tests ==="
echo ""

output_fmt=$(
  unset FOUNDRY_LOG_LEVEL
  unset CONTAINER_VERBOSE
  export LOG_NAME="FormatTest"
  # shellcheck source=src/logging.sh
  source "${LOGGING_SH}"
  log_info "format-check"
)

# Check that log line contains: LOG_NAME | timestamp | [level] message
# Strip ANSI codes first
stripped_fmt=$(echo "${output_fmt}" | sed $'s/\e\\[[0-9;]*m//g')
if echo "${stripped_fmt}" | grep -qE 'FormatTest \| [0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2} \| \['; then
  PASS_COUNT=$((PASS_COUNT + 1))
  echo "  PASS: Log format matches '{name} | {timestamp} | [{level}] {msg}'"
else
  FAIL_COUNT=$((FAIL_COUNT + 1))
  echo "  FAIL: Log format does not match expected pattern"
  echo "  Output: ${output_fmt}"
fi

# ── Summary ──────────────────────────────────────────────────────────────────

echo ""
echo "=== Summary ==="
echo "  Passed: ${PASS_COUNT}"
echo "  Failed: ${FAIL_COUNT}"
echo ""

if [[ ${FAIL_COUNT} -gt 0 ]]; then
  exit 1
fi
exit 0
