#!/bin/bash
# check_health.sh — FoundryVTT Docker health check
#
# Usage:
#   check_health.sh           Default mode: silent, exit 0 (healthy) or 1 (unhealthy).
#                             Compatible with Docker HEALTHCHECK.
#   check_health.sh --json    Machine-readable mode: prints a single JSON object to
#                             stdout, then exits 0 (healthy) or 1 (unhealthy).
#
# Machine-readable mode is also activated by setting HEALTHCHECK_JSON=1.
#
# JSON output schema:
#   {
#     "status":      "ok" | "error",
#     "code":        "OK" | "CONN_REFUSED" | "TIMEOUT" | "AUTH_REDIRECT" |
#                    "HTTP_ERROR" | "CONFIG_MISSING" | "CURL_ERROR",
#     "http_status": <int|null>,
#     "url":         "<url>",
#     "message":     "<human-readable description>"
#   }

set -euo pipefail

###############################################################################
# Parse arguments / environment
###############################################################################
JSON_MODE=false
if [[ "${HEALTHCHECK_JSON:-}" == "1" ]] || [[ "${HEALTHCHECK_JSON:-}" == "true" ]]; then
  JSON_MODE=true
fi

for arg in "$@"; do
  case "${arg}" in
    --json) JSON_MODE=true ;;
    *)
      if [[ "${JSON_MODE}" == "true" ]]; then
        # In JSON mode, emit an error for unknown flags
        echo "{\"status\":\"error\",\"code\":\"CONFIG_MISSING\",\"http_status\":null,\"url\":\"\",\"message\":\"Unknown argument: ${arg}\"}"
        exit 1
      fi
      ;;
  esac
done

###############################################################################
# Build the status URL (same logic as original)
###############################################################################
if [[ "${FOUNDRY_SSL_CERT:-}" && "${FOUNDRY_SSL_KEY:-}" ]]; then
  protocol="https"
else
  protocol="http"
fi

FOUND_PORT="${FOUNDRY_PORT:-30000}"

if [[ "${FOUNDRY_ROUTE_PREFIX:-}" ]]; then
  STATUS_URL="${protocol}://localhost:${FOUND_PORT}/${FOUNDRY_ROUTE_PREFIX}/api/status"
else
  STATUS_URL="${protocol}://localhost:${FOUND_PORT}/api/status"
fi

###############################################################################
# Default mode — exact original behavior for Docker HEALTHCHECK compatibility
###############################################################################
if [[ "${JSON_MODE}" == "false" ]]; then
  /usr/bin/curl --cookie-jar /tmp/healthcheck-cookiejar.txt \
    --cookie /tmp/healthcheck-cookiejar.txt --insecure --fail --silent \
    "${STATUS_URL}" || exit 1
  exit 0
fi

###############################################################################
# Machine-readable (JSON) mode
###############################################################################

# Helper: emit JSON line and exit
emit_json() {
  local status="$1" code="$2" http_status="$3" message="$4"
  # Use printf to avoid trailing newline issues; jq not guaranteed in container
  printf '{"status":"%s","code":"%s","http_status":%s,"url":"%s","message":"%s"}\n' \
    "${status}" "${code}" "${http_status}" "${STATUS_URL}" "${message}"
}

COOKIE_JAR="/tmp/healthcheck-cookiejar.txt"
HTTP_CODE_FILE="$(mktemp /tmp/healthcheck-httpcode.XXXXXX)"
trap 'rm -f "${HTTP_CODE_FILE}"' EXIT

# Run curl WITHOUT --fail so we can capture the HTTP status code on errors.
# Capture curl's exit code to distinguish connection-level failures from HTTP errors.
CURL_EXIT=0
/usr/bin/curl \
  --cookie-jar "${COOKIE_JAR}" \
  --cookie "${COOKIE_JAR}" \
  --insecure \
  --silent \
  --output /dev/null \
  --write-out '%{http_code}' \
  --max-time 5 \
  "${STATUS_URL}" > "${HTTP_CODE_FILE}" 2>/dev/null || CURL_EXIT=$?

HTTP_CODE="$(cat "${HTTP_CODE_FILE}" 2>/dev/null || echo "000")"

# --- Classify the result ---

# 1) curl itself failed (connection-level issue)
if [[ "${CURL_EXIT}" -ne 0 ]]; then
  case "${CURL_EXIT}" in
    7)
      emit_json "error" "CONN_REFUSED" "null" "Service not listening on port ${FOUND_PORT} (connection refused)"
      exit 1
      ;;
    28)
      emit_json "error" "TIMEOUT" "null" "Health check timed out after 5 seconds"
      exit 1
      ;;
    *)
      emit_json "error" "CURL_ERROR" "null" "curl failed with exit code ${CURL_EXIT}"
      exit 1
      ;;
  esac
fi

# 2) HTTP success (2xx)
if [[ "${HTTP_CODE}" =~ ^2[0-9]{2}$ ]]; then
  emit_json "ok" "OK" "${HTTP_CODE}" "FoundryVTT is healthy"
  exit 0
fi

# 3) Auth / redirect anomalies (3xx, 401, 403)
if [[ "${HTTP_CODE}" =~ ^3[0-9]{2}$ ]] || [[ "${HTTP_CODE}" == "401" ]] || [[ "${HTTP_CODE}" == "403" ]]; then
  emit_json "error" "AUTH_REDIRECT" "${HTTP_CODE}" "Unexpected redirect or authentication failure (HTTP ${HTTP_CODE})"
  exit 1
fi

# 4) All other non-2xx HTTP responses
emit_json "error" "HTTP_ERROR" "${HTTP_CODE}" "Unhealthy HTTP response (HTTP ${HTTP_CODE})"
exit 1
