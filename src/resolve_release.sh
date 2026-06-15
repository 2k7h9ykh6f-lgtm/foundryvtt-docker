#!/bin/bash

# resolve_release.sh — Foundry VTT version resolution and release URL acquisition.
#
# This library is meant to be sourced by entrypoint.sh.  It expects the caller
# to provide the standard logging functions: log, log_debug, log_warn, log_error.
#
# Functions:
#   validate_version_format <version>
#   check_installed_version <version> <base_dir>
#   resolve_presigned_url <cookiejar> <node_user_agent> <version>

# ── Error codes ──────────────────────────────────────────────────────────────
readonly RESOLVE_ERR_INVALID_VERSION=2
readonly RESOLVE_ERR_NO_URL=3

# ── validate_version_format ──────────────────────────────────────────────────
# Validate that a Foundry VTT version string matches the expected
# "generation.build" format (e.g. "14.363").
#
# Arguments:
#   $1  Version string to validate.
#
# Returns:
#   0  Valid format.
#   1  Invalid format.
validate_version_format() {
  local version="${1:-}"
  if [[ -z "${version}" ]]; then
    log_error "Version string is empty."
    return 1
  fi
  if [[ ! "${version}" =~ ^[0-9]+\.[0-9]+$ ]]; then
    log_error "Invalid FOUNDRY_VERSION format: \"${version}\"."
    log_error "Expected \"generation.build\" (e.g. \"14.363\")."
    return 1
  fi
  return 0
}

# ── check_installed_version ──────────────────────────────────────────────────
# Compare the installed Foundry VTT version against the requested version.
#
# Reads generation.build from <base_dir>/resources/app/package.json (if it
# exists) and compares it to the requested version.
#
# Arguments:
#   $1  Requested version (e.g. "14.363").
#   $2  Base directory containing resources/app/package.json.
#
# Outputs:
#   "true"   if installation is required (version mismatch or not installed).
#   "false"  if the installed version matches the requested version.
check_installed_version() {
  local requested_version="${1}"
  local base_dir="${2}"
  local package_json="${base_dir}/resources/app/package.json"

  if [ -f "${package_json}" ]; then
    local installed_version
    installed_version=$(jq --raw-output '.release | "\(.generation).\(.build)"' "${package_json}")
    log "Foundry Virtual Tabletop ${installed_version} is installed."
    if [ "${requested_version}" != "${installed_version}" ]; then
      log "Requested version (${requested_version}) from FOUNDRY_VERSION differs."
      log "Uninstalling version ${installed_version}."
      rm -r "${base_dir}/resources"
      echo "true"
    else
      echo "false"
    fi
  else
    log "No Foundry Virtual Tabletop installation detected."
    echo "true"
  fi
}

# ── resolve_presigned_url ────────────────────────────────────────────────────
# Resolve a presigned download URL for a Foundry VTT release.
#
# Precedence:
#   1. FOUNDRY_RELEASE_URL environment variable (direct URL, no API calls).
#   2. FOUNDRY_USERNAME + FOUNDRY_PASSWORD credentials (authenticate then fetch).
#
# Arguments:
#   $1  Path to the cookie jar file.
#   $2  User-agent string for node-fetch requests.
#   $3  Foundry VTT version (e.g. "14.363").
#
# Environment variables read:
#   FOUNDRY_RELEASE_URL        If set, used directly as the download URL.
#   FOUNDRY_USERNAME           Username for foundryvtt.com authentication.
#   FOUNDRY_PASSWORD           Password for foundryvtt.com authentication.
#   CONTAINER_VERBOSE          If set, enables debug logging in JS tools.
#   CONTAINER_URL_FETCH_RETRY Number of retries for get_release_url.js.
#
# Outputs:
#   Prints the resolved presigned URL to stdout (may be empty).
#
# Returns:
#   0  URL resolved successfully (non-empty output).
#   1  No URL could be resolved (empty output).
resolve_presigned_url() {
  local cookiejar_file="${1}"
  local node_user_agent="${2}"
  local foundry_version="${3}"
  local presigned_url=""

  # Method 1: Direct URL from environment variable.
  if [ "${FOUNDRY_RELEASE_URL:-}" ]; then
    log "Using FOUNDRY_RELEASE_URL to download release."
    presigned_url="${FOUNDRY_RELEASE_URL}"
  fi

  # Method 2: Authenticated fetch via credentials.
  if [[ "${FOUNDRY_USERNAME:-}" && "${FOUNDRY_PASSWORD:-}" ]]; then
    log "Using FOUNDRY_USERNAME and FOUNDRY_PASSWORD to authenticate."

    # Temporarily disable errexit to capture failure from authenticate.js
    set +e
    ./authenticate.js ${CONTAINER_VERBOSE+--log-level=debug} \
      --user-agent="${node_user_agent}" \
      "${FOUNDRY_USERNAME}" "${FOUNDRY_PASSWORD}" "${cookiejar_file}"
    local auth_exit_code=$?
    set -e

    if [ ${auth_exit_code} -ne 0 ]; then
      log_warn "Authentication failed with exit code ${auth_exit_code}."
      rm -f "${cookiejar_file}"
    elif [[ ! "${presigned_url:-}" ]]; then
      # If the presigned_url wasn't set by FOUNDRY_RELEASE_URL, generate one now.
      log "Using authenticated credentials to fetch release URL."
      set +e
      presigned_url=$(./get_release_url.js ${CONTAINER_VERBOSE+--log-level=debug} \
        ${CONTAINER_URL_FETCH_RETRY+--retry=${CONTAINER_URL_FETCH_RETRY}} \
        --user-agent="${node_user_agent}" \
        "${cookiejar_file}" "${foundry_version}")
      local url_exit_code=$?
      set -e

      if [ ${url_exit_code} -ne 0 ]; then
        log_warn "Release URL fetch failed with exit code ${url_exit_code}."
        presigned_url=""
      fi
    fi
  fi

  # Validate the resolved URL is non-empty.
  if [[ "${presigned_url:-}" ]]; then
    echo "${presigned_url}"
    return 0
  else
    return 1
  fi
}
