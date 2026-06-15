#!/bin/bash

# validate_permissions.sh — sourceable bash library for pre-flight permission checks.
# Source this file from entrypoint.sh before use.
#
# Exposes:
#   validate_permissions <data_dir>  — run all pre-flight checks in order
#
# Depends on logging.sh being sourced by the caller before this file.

# Deprecated environment variables that should trigger a warning if set.
DEPRECATED_ENVS="CONTAINER_PRESERVE_OWNER FOUNDRY_UID FOUNDRY_GID TIMEZONE"

# _validate_deprecated_envs
#   Warn about deprecated environment variables that are no longer consumed.
_validate_deprecated_envs() {
  local deprecated_env
  for deprecated_env in $DEPRECATED_ENVS; do
    if [ -n "${!deprecated_env:-}" ]; then
      log_warn "The environment variable \"$deprecated_env\" is deprecated and will be ignored."
    fi
  done
}

# _validate_identity
#   Log the current UID/GID for debugging purposes.
_validate_identity() {
  log_debug "Running as: $(id)"
}

# _validate_uid_sanity
#   Warn if running as root (UID 0) or a system user (UID < 1000).
#   These are warnings only — not fatal.
_validate_uid_sanity() {
  local current_uid
  current_uid=$(id -u)
  if [ "$current_uid" -eq 0 ]; then
    log_warn "Running as root (UID 0). This is not recommended for security reasons."
  elif [ "$current_uid" -lt 1000 ] && [ "$(id -un)" != "node" ]; then
    log_warn "Running as UID $current_uid, which is in the system range (< 1000)."
    log_warn "This may indicate a misconfiguration. Expected UID 1000 (node) or >= 1000."
  fi
}

# _validate_executable_files
#   Verify that critical shell scripts are executable.
#   Only checks files that exist — compiled JS files (set_options.js, etc.)
#   are not checked here as they are created during the Docker build.
#   Fatal if any existing required file is not executable.
_validate_executable_files() {
  local required_files=("launcher.sh" "check_health.sh")
  local file
  local failed=0
  for file in "${required_files[@]}"; do
    if [ ! -f "$file" ]; then
      log_debug "Executable check skipped: $file (not found)"
      continue
    fi
    if [ ! -x "$file" ]; then
      log_error "Required file '$file' is not executable."
      failed=1
    else
      log_debug "Executable check passed: $file"
    fi
  done
  if [ "$failed" -ne 0 ]; then
    log_error "Aborting due to non-executable required files."
    exit 1
  fi
}

# _validate_data_dir_permissions <data_dir>
#   Test read/write/delete permissions on the data directory.
#   Fatal if any test fails.
_validate_data_dir_permissions() {
  local data_dir="$1"
  local permissions_test_file="${data_dir}/.container-permissions-test.txt"
  local permission_test_failed=0

  log_debug "Testing permissions on ${permissions_test_file}"

  # Test write
  if ! touch "${permissions_test_file}" 2> /dev/null; then
    log_error "Volume write test failed."
    permission_test_failed=1
  else
    log_debug "Volume write test succeeded."
  fi

  # Test read
  if ! cat "${permissions_test_file}" > /dev/null 2>&1; then
    log_error "Volume read test failed."
    permission_test_failed=1
  else
    log_debug "Volume read test succeeded."
  fi

  # Test delete
  if ! rm -f "${permissions_test_file}" 2> /dev/null; then
    log_error "Volume delete test failed."
    permission_test_failed=1
  else
    log_debug "Volume delete test succeeded."
  fi

  if [ "${permission_test_failed}" -ne 0 ]; then
    log_error "Aborting due to insufficient permissions on ${data_dir}"
    log_error "Container running as uid:gid: $(id -u):$(id -g)"
    log_error "For more information see the discussion at: https://github.com/felddy/foundryvtt-docker/discussions/1197"
    exit 1
  fi
  log_debug "All data directory permissions tests succeeded."
}

# _validate_config_dir <data_dir>
#   Ensure the Config subdirectory exists and is creatable.
#   Fatal if mkdir fails.
_validate_config_dir() {
  local data_dir="$1"
  local config_dir="${data_dir}/Config"
  log_debug "Ensuring ${config_dir} directory exists."
  if ! mkdir -p "${config_dir}" 2> /dev/null; then
    log_error "Failed to create config directory: ${config_dir}"
    log_error "Container running as uid:gid: $(id -u):$(id -g)"
    exit 1
  fi
  log_debug "Config directory check succeeded."
}

# _validate_umask
#   Validate CONTAINER_UMASK format if set.
#   Warn if the format is invalid (not a valid octal number).
#   Not fatal — launcher.sh will attempt to apply it and warn on failure.
_validate_umask() {
  if [[ "${CONTAINER_UMASK:-}" ]]; then
    # Valid umask: 3 or 4 octal digits (e.g., 022, 0022, 077)
    if ! [[ "${CONTAINER_UMASK}" =~ ^[0-7]{3,4}$ ]]; then
      log_warn "CONTAINER_UMASK='${CONTAINER_UMASK}' is not a valid octal umask (expected 3-4 octal digits, e.g., 0022)."
    else
      log_debug "CONTAINER_UMASK='${CONTAINER_UMASK}' format is valid."
    fi
  fi
}

# validate_permissions <data_dir>
#   Public API: run all pre-flight checks in order.
#   Exits with code 1 if any fatal check fails.
validate_permissions() {
  local data_dir="$1"

  log_debug "Starting pre-flight permission validation for data directory: ${data_dir}"

  # 1. Deprecated environment variables (warn only)
  _validate_deprecated_envs

  # 2. Identity logging (debug only)
  _validate_identity

  # 3. UID/GID sanity (warn only)
  _validate_uid_sanity

  # 4. Critical files are executable (fatal)
  _validate_executable_files

  # 5. Data directory read/write/delete (fatal)
  _validate_data_dir_permissions "$data_dir"

  # 6. Config directory creatable (fatal)
  _validate_config_dir "$data_dir"

  # 7. CONTAINER_UMASK format (warn only)
  _validate_umask

  log_debug "Pre-flight permission validation complete."
}
