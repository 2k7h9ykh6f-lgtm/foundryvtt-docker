#!/bin/bash

if [[ "${FOUNDRY_SSL_CERT:-}" && "${FOUNDRY_SSL_KEY:-}" ]]; then
  protocol="https"
else
  protocol="http"
fi

if [[ "${FOUNDRY_ROUTE_PREFIX:-}" ]]; then
  STATUS_URL="${protocol}://localhost:30000/${FOUNDRY_ROUTE_PREFIX}/api/status"
else
  STATUS_URL="${protocol}://localhost:30000/api/status"
fi

# Configurable curl path for testability; defaults to the original absolute path.
CURL="${CURL:-/usr/bin/curl}"

# Emit a single-line JSON object to stdout.  All values are controlled strings
# so no escaping is needed.  Works without jq.
emit_json() {
  local status="$1" curl_exit_code="$2" http_code="$3"
  local ts http_code_json
  ts=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
  if [[ "$http_code" == "000" || -z "$http_code" ]]; then
    http_code_json="null"
  else
    http_code_json="$http_code"
  fi
  printf '{"status":"%s","curl_exit":%d,"http_code":%s,"url":"%s","timestamp":"%s"}\n' \
    "$status" "$curl_exit_code" "$http_code_json" "$STATUS_URL" "$ts"
}

if [[ "${1:-}" == "--json" ]]; then
  # --- Machine-readable mode ---

  # Verify curl binary is available
  if [[ ! -x "$CURL" ]]; then
    emit_json "config_missing" 127 ""
    exit 1
  fi

  # Run curl WITHOUT --fail so we can capture the actual HTTP status code.
  http_code=$("$CURL" --cookie-jar /tmp/healthcheck-cookiejar.txt \
    --cookie /tmp/healthcheck-cookiejar.txt --insecure --silent \
    --output /dev/null --write-out '%{http_code}' \
    "${STATUS_URL}" 2>/dev/null)
  curl_exit=$?

  # Transport-level failure
  if [[ $curl_exit -ne 0 ]]; then
    case $curl_exit in
      6|7|28) emit_json "connection_refused" "$curl_exit" "$http_code" ;;
      *)      emit_json "config_missing" "$curl_exit" "$http_code" ;;
    esac
    exit 1
  fi

  # Classify by HTTP status code
  case "${http_code}" in
    2[0-9][0-9]) emit_json "healthy" 0 "$http_code"; exit 0 ;;
    3[0-9][0-9]) emit_json "auth_redirect" 0 "$http_code"; exit 1 ;;
    *)           emit_json "http_error" 0 "$http_code"; exit 1 ;;
  esac

else
  # --- Default mode: original behaviour, unchanged ---
  "$CURL" --cookie-jar /tmp/healthcheck-cookiejar.txt \
    --cookie /tmp/healthcheck-cookiejar.txt --insecure --fail --silent \
    "${STATUS_URL}" || exit 1
fi
