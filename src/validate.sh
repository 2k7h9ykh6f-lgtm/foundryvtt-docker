#!/bin/bash

# validate.sh — sourceable shell library providing reusable path and value
# validation functions for the foundryvtt-docker container.
#
# All functions return 0 on success and 1 on failure.  They log diagnostics
# via log_debug / log_error (from logging.sh) but never call exit — the
# caller retains full control over error-exit policy.
#
# Prerequisites: logging.sh must be sourced by the caller before this file.

# validate_writable_dir <dir_path>
#   Verify that <dir_path> exists as a directory and supports write, read,
#   and delete operations by creating a temporary probe file.
#   Returns: 0 if all three operations succeed, 1 otherwise.
validate_writable_dir() {
  local dir="${1:-}"

  if [[ -z "${dir}" ]]; then
    log_error "validate_writable_dir: no directory path provided."
    return 1
  fi

  if [[ ! -d "${dir}" ]]; then
    log_error "Directory does not exist: ${dir}"
    return 1
  fi

  local probe_file="${dir}/.validate-probe-$$"
  local failed=0

  if ! touch "${probe_file}" 2>/dev/null; then
    log_error "Write test failed on directory: ${dir}"
    failed=1
  else
    log_debug "validate_writable_dir: write test passed for ${dir}"
    if ! cat "${probe_file}" >/dev/null 2>&1; then
      log_error "Read test failed on directory: ${dir}"
      failed=1
    else
      log_debug "validate_writable_dir: read test passed for ${dir}"
    fi
    if ! rm -f "${probe_file}" 2>/dev/null; then
      log_error "Delete test failed on directory: ${dir}"
      failed=1
    else
      log_debug "validate_writable_dir: delete test passed for ${dir}"
    fi
  fi

  if [[ "${failed}" -ne 0 ]]; then
    return 1
  fi

  log_debug "validate_writable_dir: all tests passed for ${dir}"
  return 0
}

# validate_required_file <file_path> [description]
#   Check that <file_path> exists and is a regular file.
#   Returns: 0 if the file exists, 1 if missing.
validate_required_file() {
  local file_path="${1:-}"
  local description="${2:-file}"

  if [[ -z "${file_path}" ]]; then
    log_error "validate_required_file: no file path provided."
    return 1
  fi

  if [[ ! -f "${file_path}" ]]; then
    log_error "Required ${description} not found: ${file_path}"
    return 1
  fi

  log_debug "validate_required_file: ${description} found at ${file_path}"
  return 0
}

# validate_executable_file <file_path> [description]
#   Check that <file_path> exists and has the executable bit set.
#   Returns: 0 if executable, 1 otherwise.
validate_executable_file() {
  local file_path="${1:-}"
  local description="${2:-executable}"

  if [[ -z "${file_path}" ]]; then
    log_error "validate_executable_file: no file path provided."
    return 1
  fi

  if [[ ! -x "${file_path}" ]]; then
    log_error "Required ${description} not found or not executable: ${file_path}"
    return 1
  fi

  log_debug "validate_executable_file: ${description} OK at ${file_path}"
  return 0
}

# validate_positive_integer <value> <name>
#   Check that <value> is a positive integer (> 0).
#   Returns: 0 if valid, 1 otherwise.
validate_positive_integer() {
  local value="${1:-}"
  local name="${2:-value}"

  if [[ -z "${value}" ]]; then
    log_error "${name} is not set or empty."
    return 1
  fi

  if ! [[ "${value}" =~ ^[0-9]+$ ]] || [[ "${value}" -le 0 ]]; then
    log_error "${name} must be a positive integer.  Found: ${value}"
    return 1
  fi

  log_debug "validate_positive_integer: ${name}=${value} is valid."
  return 0
}
