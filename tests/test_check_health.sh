#!/bin/bash
# test_check_health.sh — local verification for src/check_health.sh
#
# Uses mock curl scripts (via the CURL env-var override) so no network or
# running container is required.
#
# Usage:  bash tests/test_check_health.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CHECK_HEALTH="${SCRIPT_DIR}/../src/check_health.sh"
TEMP_DIR=""
PASS=0
FAIL=0

# ── helpers ──────────────────────────────────────────────────────────────

cleanup() { [[ -n "$TEMP_DIR" ]] && rm -rf "$TEMP_DIR"; }
trap cleanup EXIT
TEMP_DIR=$(mktemp -d)

# Create a mock curl script that returns a given exit code.
# In JSON mode (--write-out present) it also prints the supplied http_code.
create_mock_curl() {
  local exit_code="$1" http_code="${2:-000}"
  local mock_path="${TEMP_DIR}/mock_curl_${exit_code}_${http_code}"
  cat > "$mock_path" << MOCK
#!/bin/bash
for arg in "\$@"; do
  if [[ "\$arg" == *"%{http_code}"* ]]; then
    echo -n "${http_code}"
    exit ${exit_code}
  fi
done
exit ${exit_code}
MOCK
  chmod +x "$mock_path"
  echo "$mock_path"
}

run_check() {
  # Run check_health.sh, capture stdout and exit code.
  # Arguments after -- are forwarded to the script.
  local curl_path="$1"; shift
  local output exit_code
  output=$(CURL="$curl_path" bash "$CHECK_HEALTH" "$@" 2>/dev/null) || true
  # Re-run to get exit code (set -e would abort otherwise)
  CURL="$curl_path" bash "$CHECK_HEALTH" "$@" >/dev/null 2>&1 && exit_code=0 || exit_code=$?
  echo "${exit_code}|${output}"
}

assert_exit() {
  local label="$1" actual="$2" expected="$3"
  if [[ "$actual" == "$expected" ]]; then
    echo "  PASS  exit=$actual"
    ((++PASS))
  else
    echo "  FAIL  exit: expected=$expected actual=$actual  [$label]"
    ((++FAIL))
  fi
}

assert_json_field() {
  local label="$1" json="$2" field="$3" expected="$4"
  local actual
  actual=$(echo "$json" | python3 -c "
import sys, json
d = json.load(sys.stdin)
v = d.get('$field')
print('null' if v is None else v)
" 2>/dev/null) || actual="<parse error>"
  if [[ "$actual" == "$expected" ]]; then
    echo "  PASS  $field=$actual"
    ((++PASS))
  else
    echo "  FAIL  $field: expected=$expected actual=$actual  [$label]"
    ((++FAIL))
  fi
}

assert_json_valid() {
  local label="$1" json="$2"
  if echo "$json" | python3 -c "import sys,json; json.load(sys.stdin)" 2>/dev/null; then
    echo "  PASS  valid JSON"
    ((++PASS))
  else
    echo "  FAIL  invalid JSON  [$label]"
    ((++FAIL))
  fi
}

assert_no_stdout() {
  local label="$1" output="$2"
  if [[ -z "$output" ]]; then
    echo "  PASS  no stdout (default mode)"
    ((++PASS))
  else
    echo "  FAIL  expected no stdout, got: $output  [$label]"
    ((++FAIL))
  fi
}

# ── test cases ───────────────────────────────────────────────────────────

echo "=== Test 1: default mode — healthy (curl exits 0) ==="
mock=$(create_mock_curl 0 200)
result=$(run_check "$mock")
exit_code="${result%%|*}"
output="${result#*|}"
assert_exit "default-healthy" "$exit_code" "0"
assert_no_stdout "default-healthy" "$output"

echo ""
echo "=== Test 2: default mode — connection refused (curl exits 7) ==="
mock=$(create_mock_curl 7)
result=$(run_check "$mock")
exit_code="${result%%|*}"
output="${result#*|}"
assert_exit "default-connrefused" "$exit_code" "1"

echo ""
echo "=== Test 3: --json mode — healthy (HTTP 200) ==="
mock=$(create_mock_curl 0 200)
result=$(run_check "$mock" --json)
exit_code="${result%%|*}"
output="${result#*|}"
assert_exit "json-healthy" "$exit_code" "0"
assert_json_valid "json-healthy" "$output"
assert_json_field "json-healthy" "$output" "status" "healthy"
assert_json_field "json-healthy" "$output" "http_code" "200"

echo ""
echo "=== Test 4: --json mode — connection refused (curl exit 7) ==="
mock=$(create_mock_curl 7 000)
result=$(run_check "$mock" --json)
exit_code="${result%%|*}"
output="${result#*|}"
assert_exit "json-connrefused" "$exit_code" "1"
assert_json_valid "json-connrefused" "$output"
assert_json_field "json-connrefused" "$output" "status" "connection_refused"
assert_json_field "json-connrefused" "$output" "curl_exit" "7"
assert_json_field "json-connrefused" "$output" "http_code" "null"

echo ""
echo "=== Test 5: --json mode — timeout (curl exit 28) ==="
mock=$(create_mock_curl 28 000)
result=$(run_check "$mock" --json)
exit_code="${result%%|*}"
output="${result#*|}"
assert_exit "json-timeout" "$exit_code" "1"
assert_json_valid "json-timeout" "$output"
assert_json_field "json-timeout" "$output" "status" "connection_refused"
assert_json_field "json-timeout" "$output" "curl_exit" "28"

echo ""
echo "=== Test 6: --json mode — HTTP 403 (http_error) ==="
mock=$(create_mock_curl 0 403)
result=$(run_check "$mock" --json)
exit_code="${result%%|*}"
output="${result#*|}"
assert_exit "json-403" "$exit_code" "1"
assert_json_valid "json-403" "$output"
assert_json_field "json-403" "$output" "status" "http_error"
assert_json_field "json-403" "$output" "http_code" "403"

echo ""
echo "=== Test 7: --json mode — HTTP 302 (auth_redirect) ==="
mock=$(create_mock_curl 0 302)
result=$(run_check "$mock" --json)
exit_code="${result%%|*}"
output="${result#*|}"
assert_exit "json-302" "$exit_code" "1"
assert_json_valid "json-302" "$output"
assert_json_field "json-302" "$output" "status" "auth_redirect"
assert_json_field "json-302" "$output" "http_code" "302"

echo ""
echo "=== Test 8: --json mode — curl binary missing (config_missing) ==="
result=$(run_check "/nonexistent/curl" --json)
exit_code="${result%%|*}"
output="${result#*|}"
assert_exit "json-missing-curl" "$exit_code" "1"
assert_json_valid "json-missing-curl" "$output"
assert_json_field "json-missing-curl" "$output" "status" "config_missing"
assert_json_field "json-missing-curl" "$output" "curl_exit" "127"
assert_json_field "json-missing-curl" "$output" "http_code" "null"

# ── summary ──────────────────────────────────────────────────────────────

echo ""
echo "==============================="
echo "  PASSED: $PASS   FAILED: $FAIL"
echo "==============================="
[[ $FAIL -eq 0 ]] && exit 0 || exit 1
