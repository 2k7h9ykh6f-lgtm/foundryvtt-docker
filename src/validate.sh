#!/bin/bash

# validate.sh — sourceable bash library for path and environment validation.
# Source this file after logging.sh.  Depends on log_debug and log_error.
#
# Exposes:
#   require_file <path> [label]         — exit 1 if file does not exist
#   require_dir <path> [label]          — exit 1 if directory does not exist
#   require_executable <path> [label]   — exit 1 if file is not executable
#   require_writable_dir <path> [label] — exit 1 if dir fails write/read/delete test
#   require_env <var_name> [label]      — exit 1 if env var is unset or empty

# _validate_fail <path> <reason> [label]
#   Internal helper: log a consistent error block and exit 1.
_validate_fail() {
  local path="${1}"
  local reason="${2}"
  local label="${3:-}"
  if [[ -n "${label}" ]]; then
    log_error "Validation failed for ${label}: ${reason}"
  else
    log_error "Validation failed: ${reason}"
  fi
  log_error "  Path: ${path}"
  log_error "  Running as uid:gid: $(id -u):$(id -g)"
  exit 1
}

# require_file <path> [label]
#   Exit 1 if the file at <path> does not exist.
require_file() {
  local path="${1}"
  local label="${2:-${path}}"
  log_debug "require_file: checking ${path}"
  if [[ ! -f "${path}" ]]; then
    _validate_fail "${path}" "File not found" "${label}"
  fi
}

# require_dir <path> [label]
#   Exit 1 if the directory at <path> does not exist.
require_dir() {
  local path="${1}"
  local label="${2:-${path}}"
  log_debug "require_dir: checking ${path}"
  if [[ ! -d "${path}" ]]; then
    _validate_fail "${path}" "Directory not found" "${label}"
  fi
}

# require_executable <path> [label]
#   Exit 1 if the file at <path> does not exist or is not executable.
require_executable() {
  local path="${1}"
  local label="${2:-${path}}"
  log_debug "require_executable: checking ${path}"
  if [[ ! -f "${path}" ]]; then
    _validate_fail "${path}" "File not found" "${label}"
  fi
  if [[ ! -x "${path}" ]]; then
    _validate_fail "${path}" "File is not executable" "${label}"
  fi
}

# require_writable_dir <path> [label]
#   Perform a write/read/delete test on <path>.  Exit 1 if any step fails.
#   Preserves the original entrypoint.sh behaviour: all three tests run
#   regardless of earlier failures so every problem is reported.
require_writable_dir() {
  local path="${1}"
  local label="${2:-${path}}"
  local test_file="${path}/.container-permissions-test.txt"
  local failed=0

  log_debug "require_writable_dir: testing permissions on ${path}"

  if [[ ! -d "${path}" ]]; then
    _validate_fail "${path}" "Directory not found" "${label}"
  fi

  if ! touch "${test_file}" 2> /dev/null; then
    log_error "Volume write test failed."
    failed=1
  else
    log_debug "Volume write test succeeded."
  fi
  if ! cat "${test_file}" > /dev/null 2>&1; then
    log_error "Volume read test failed."
    failed=1
  else
    log_debug "Volume read test succeeded."
  fi
  if ! rm -f "${test_file}" 2> /dev/null; then
    log_error "Volume delete test failed."
    failed=1
  else
    log_debug "Volume delete test succeeded."
  fi
  if [[ "${failed}" -ne 0 ]]; then
    log_error "Aborting due to insufficient permissions on ${path}"
    log_error "Container running as uid:gid: $(id -u):$(id -g)"
    log_error "For more information see the discussion at: https://github.com/felddy/foundryvtt-docker/discussions/1197"
    exit 1
  fi
  log_debug "All permissions tests on ${path} succeeded."
}

# require_env <var_name> [label]
#   Exit 1 if the environment variable named <var_name> is unset or empty.
require_env() {
  local var_name="${1}"
  local label="${2:-${var_name}}"
  log_debug "require_env: checking \$${var_name}"
  if [[ -z "${!var_name:-}" ]]; then
    log_error "Validation failed for ${label}: Required environment variable ${var_name} is not set."
    exit 1
  fi
}
