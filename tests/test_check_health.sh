#!/bin/bash
# test_check_health.sh — standalone tests for src/check_health.sh
#
# Run:  bash tests/test_check_health.sh
#
# Uses short-lived Python HTTP servers to simulate each failure branch.
# No Docker image required.

set -u

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
HEALTH_SCRIPT="${REPO_DIR}/src/check_health.sh"

PASS=0
FAIL=0
TEST_PORT=""
SERVER_PID=""

# Cleanup any background server on exit
cleanup() {
  if [[ -n "${SERVER_PID}" ]] && kill -0 "${SERVER_PID}" 2>/dev/null; then
    kill "${SERVER_PID}" 2>/dev/null
    wait "${SERVER_PID}" 2>/dev/null
  fi
}
trap cleanup EXIT

###############################################################################
# Helpers
###############################################################################

# Find a free TCP port
find_free_port() {
  python3 -c '
import socket
s = socket.socket()
s.bind(("127.0.0.1", 0))
print(s.getsockname()[1])
s.close()
'
}

# Start a Python HTTP server returning a given status code on a given port.
# Usage: start_server <port> <status_code>
start_server() {
  local port="$1" status="$2"
  python3 -c "
import http.server, socketserver, sys

class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(${status})
        self.send_header('Content-Type', 'text/plain')
        self.end_headers()
        self.wfile.write(b'${status} response')
    def log_message(self, *a):
        pass  # suppress logs

socketserver.TCPServer.allow_reuse_address = True
with socketserver.TCPServer(('127.0.0.1', ${port}), Handler) as httpd:
    httpd.serve_forever()
" &
  SERVER_PID=$!
  # Wait until server is actually listening
  for _i in $(seq 1 30); do
    if python3 -c "import socket; s=socket.socket(); s.settimeout(0.2); s.connect(('127.0.0.1',${port})); s.close()" 2>/dev/null; then
      return 0
    fi
    sleep 0.1
  done
  echo "ERROR: server on port ${port} did not start in time" >&2
  return 1
}

# Stop the current mock server
stop_server() {
  if [[ -n "${SERVER_PID}" ]] && kill -0 "${SERVER_PID}" 2>/dev/null; then
    kill "${SERVER_PID}" 2>/dev/null
    wait "${SERVER_PID}" 2>/dev/null
  fi
  SERVER_PID=""
}

# Run one test case
# Usage: run_test <name> <expected_exit> <expected_json_code|_-> <extra_env...> -- <extra_args...>
run_test() {
  local name="$1"; shift
  local expect_exit="$1"; shift
  local expect_code="$1"; shift  # "_" means skip JSON code check

  # Collect env vars (everything before --)
  local -a env_vars=()
  local -a extra_args=()
  local past_sep=false
  for arg in "$@"; do
    if [[ "${arg}" == "--" ]]; then
      past_sep=true
      continue
    fi
    if [[ "${past_sep}" == "true" ]]; then
      extra_args+=("${arg}")
    else
      env_vars+=("${arg}")
    fi
  done

  # Run the health check
  local actual_exit=0
  local output=""
  output=$(env "${env_vars[@]}" bash "${HEALTH_SCRIPT}" "${extra_args[@]}" 2>&1) || actual_exit=$?

  # Check exit code
  if [[ "${actual_exit}" -ne "${expect_exit}" ]]; then
    echo "  FAIL: ${name}"
    echo "        expected exit=${expect_exit}, got exit=${actual_exit}"
    echo "        output: ${output}"
    FAIL=$((FAIL + 1))
    return
  fi

  # Check JSON code if requested
  if [[ "${expect_code}" != "_" ]]; then
    local actual_code=""
    actual_code=$(echo "${output}" | python3 -c "import sys,json; print(json.loads(sys.stdin.read())['code'])" 2>/dev/null) || true
    if [[ "${actual_code}" != "${expect_code}" ]]; then
      echo "  FAIL: ${name}"
      echo "        expected code=${expect_code}, got code=${actual_code}"
      echo "        output: ${output}"
      FAIL=$((FAIL + 1))
      return
    fi
  fi

  echo "  PASS: ${name}"
  PASS=$((PASS + 1))
}

###############################################################################
# Tests
###############################################################################
echo "=== check_health.sh test suite ==="
echo ""

# ---------- Default mode (Docker HEALTHCHECK compat) ----------
echo "[Default mode]"

# D1: Success — server returns 200
TEST_PORT=$(find_free_port)
start_server "${TEST_PORT}" 200
run_test "default mode: 200 → exit 0" 0 "_" \
  "FOUNDRY_PORT=${TEST_PORT}" --
stop_server

# D2: Failure — nothing listening
TEST_PORT=$(find_free_port)
run_test "default mode: nothing listening → exit 1" 1 "_" \
  "FOUNDRY_PORT=${TEST_PORT}" --

# D3: Failure — server returns 500 (curl --fail treats 4xx/5xx as failure)
TEST_PORT=$(find_free_port)
start_server "${TEST_PORT}" 500
run_test "default mode: 500 → exit 1" 1 "_" \
  "FOUNDRY_PORT=${TEST_PORT}" --
stop_server

echo ""

# ---------- JSON mode: success ----------
echo "[JSON mode — success]"

# J1: 200 → OK
TEST_PORT=$(find_free_port)
start_server "${TEST_PORT}" 200
run_test "json mode: 200 → code OK" 0 "OK" \
  "FOUNDRY_PORT=${TEST_PORT}" -- --json
stop_server

echo ""

# ---------- JSON mode: failure branches ----------
echo "[JSON mode — failures]"

# J2: Connection refused
TEST_PORT=$(find_free_port)
run_test "json mode: conn refused → CONN_REFUSED" 1 "CONN_REFUSED" \
  "FOUNDRY_PORT=${TEST_PORT}" -- --json

# J3: HTTP 500
TEST_PORT=$(find_free_port)
start_server "${TEST_PORT}" 500
run_test "json mode: 500 → HTTP_ERROR" 1 "HTTP_ERROR" \
  "FOUNDRY_PORT=${TEST_PORT}" -- --json
stop_server

# J4: HTTP 503
TEST_PORT=$(find_free_port)
start_server "${TEST_PORT}" 503
run_test "json mode: 503 → HTTP_ERROR" 1 "HTTP_ERROR" \
  "FOUNDRY_PORT=${TEST_PORT}" -- --json
stop_server

# J5: HTTP 401 → AUTH_REDIRECT
TEST_PORT=$(find_free_port)
start_server "${TEST_PORT}" 401
run_test "json mode: 401 → AUTH_REDIRECT" 1 "AUTH_REDIRECT" \
  "FOUNDRY_PORT=${TEST_PORT}" -- --json
stop_server

# J6: HTTP 403 → AUTH_REDIRECT
TEST_PORT=$(find_free_port)
start_server "${TEST_PORT}" 403
run_test "json mode: 403 → AUTH_REDIRECT" 1 "AUTH_REDIRECT" \
  "FOUNDRY_PORT=${TEST_PORT}" -- --json
stop_server

# J7: HTTP 302 → AUTH_REDIRECT
TEST_PORT=$(find_free_port)
start_server "${TEST_PORT}" 302
run_test "json mode: 302 → AUTH_REDIRECT" 1 "AUTH_REDIRECT" \
  "FOUNDRY_PORT=${TEST_PORT}" -- --json
stop_server

# J8: HTTP 404 → HTTP_ERROR
TEST_PORT=$(find_free_port)
start_server "${TEST_PORT}" 404
run_test "json mode: 404 → HTTP_ERROR" 1 "HTTP_ERROR" \
  "FOUNDRY_PORT=${TEST_PORT}" -- --json
stop_server

echo ""

# ---------- JSON mode: env-var activation ----------
echo "[JSON mode — env var activation]"

# J9: HEALTHCHECK_JSON=1 activates JSON mode without --json flag
TEST_PORT=$(find_free_port)
start_server "${TEST_PORT}" 200
run_test "env HEALTHCHECK_JSON=1 → OK" 0 "OK" \
  "FOUNDRY_PORT=${TEST_PORT}" "HEALTHCHECK_JSON=1" --
stop_server

echo ""

# ---------- JSON output validation ----------
echo "[JSON output structure]"

# J10: Validate JSON contains all required fields
TEST_PORT=$(find_free_port)
start_server "${TEST_PORT}" 200
OUTPUT=$(FOUNDRY_PORT="${TEST_PORT}" bash "${HEALTH_SCRIPT}" --json 2>&1)
MISSING_FIELDS=""
for field in status code http_status url message; do
  if ! echo "${OUTPUT}" | python3 -c "import sys,json; d=json.loads(sys.stdin.read()); assert '${field}' in d" 2>/dev/null; then
    MISSING_FIELDS="${MISSING_FIELDS} ${field}"
  fi
done
if [[ -z "${MISSING_FIELDS}" ]]; then
  echo "  PASS: json output contains all required fields"
  PASS=$((PASS + 1))
else
  echo "  FAIL: json output missing fields:${MISSING_FIELDS}"
  echo "        output: ${OUTPUT}"
  FAIL=$((FAIL + 1))
fi
stop_server

# J11: Validate http_status is an integer in success
TEST_PORT=$(find_free_port)
start_server "${TEST_PORT}" 200
OUTPUT=$(FOUNDRY_PORT="${TEST_PORT}" bash "${HEALTH_SCRIPT}" --json 2>&1)
HTTP_STATUS=$(echo "${OUTPUT}" | python3 -c "import sys,json; d=json.loads(sys.stdin.read()); print(d['http_status'])" 2>/dev/null)
if [[ "${HTTP_STATUS}" == "200" ]]; then
  echo "  PASS: http_status is 200 (integer)"
  PASS=$((PASS + 1))
else
  echo "  FAIL: expected http_status=200, got ${HTTP_STATUS}"
  FAIL=$((FAIL + 1))
fi
stop_server

# J12: Validate http_status is null in CONN_REFUSED
TEST_PORT=$(find_free_port)
OUTPUT=$(FOUNDRY_PORT="${TEST_PORT}" bash "${HEALTH_SCRIPT}" --json 2>&1)
HTTP_STATUS=$(echo "${OUTPUT}" | python3 -c "import sys,json; d=json.loads(sys.stdin.read()); print(d['http_status'])" 2>/dev/null)
if [[ "${HTTP_STATUS}" == "None" ]]; then
  echo "  PASS: http_status is null for CONN_REFUSED"
  PASS=$((PASS + 1))
else
  echo "  FAIL: expected http_status=None, got ${HTTP_STATUS}"
  FAIL=$((FAIL + 1))
fi

# J13: Validate url field contains the expected URL
TEST_PORT=$(find_free_port)
start_server "${TEST_PORT}" 200
OUTPUT=$(FOUNDRY_PORT="${TEST_PORT}" bash "${HEALTH_SCRIPT}" --json 2>&1)
URL_VAL=$(echo "${OUTPUT}" | python3 -c "import sys,json; d=json.loads(sys.stdin.read()); print(d['url'])" 2>/dev/null)
if [[ "${URL_VAL}" == "http://localhost:${TEST_PORT}/api/status" ]]; then
  echo "  PASS: url field is correct"
  PASS=$((PASS + 1))
else
  echo "  FAIL: expected url=http://localhost:${TEST_PORT}/api/status, got ${URL_VAL}"
  FAIL=$((FAIL + 1))
fi
stop_server

echo ""

# ---------- Route prefix ----------
echo "[Route prefix]"

# J14: FOUNDRY_ROUTE_PREFIX is reflected in the URL
TEST_PORT=$(find_free_port)
start_server "${TEST_PORT}" 200
OUTPUT=$(FOUNDRY_PORT="${TEST_PORT}" FOUNDRY_ROUTE_PREFIX="myprefix" bash "${HEALTH_SCRIPT}" --json 2>&1)
URL_VAL=$(echo "${OUTPUT}" | python3 -c "import sys,json; d=json.loads(sys.stdin.read()); print(d['url'])" 2>/dev/null)
if [[ "${URL_VAL}" == "http://localhost:${TEST_PORT}/myprefix/api/status" ]]; then
  echo "  PASS: route prefix reflected in url"
  PASS=$((PASS + 1))
else
  echo "  FAIL: expected url with /myprefix/, got ${URL_VAL}"
  FAIL=$((FAIL + 1))
fi
stop_server

echo ""

# ---------- Summary ----------
echo "=== Results: ${PASS} passed, ${FAIL} failed ==="
if [[ "${FAIL}" -gt 0 ]]; then
  exit 1
fi
exit 0
