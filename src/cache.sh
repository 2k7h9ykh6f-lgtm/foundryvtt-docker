#!/bin/bash

# cache.sh — sourceable bash library for Foundry VTT container cache management.
# Source this file from entrypoint.sh before use.
#
# Exposes:
#   cache_resolve_dir     — resolve CONTAINER_CACHE default (null→default path)
#   cache_init            — create, validate, and prepare the cache directory
#   cache_cleanup_stale   — remove stale temporary files from a prior run
#   cache_prune           — prune old release archives per CONTAINER_CACHE_SIZE
#
# Depends on logging.sh being sourced by the caller before this file.

# Default cache directory when CONTAINER_CACHE is unset (null).
# Shared by cache.sh and backoff.sh so the default is defined in one place.
CONTAINER_CACHE_DEFAULT="/data/container_cache"

# cache_resolve_dir
#   Apply the default-value rule for CONTAINER_CACHE:
#     unset (null)  → set to the default path (/data/container_cache)
#     empty string  → leave empty (caching disabled)
#     any other value → leave unchanged
#   This is idempotent and safe to call multiple times.
cache_resolve_dir() {
  CONTAINER_CACHE="${CONTAINER_CACHE-${CONTAINER_CACHE_DEFAULT}}"
}

# cache_init
#   Resolve the CONTAINER_CACHE default, create the directory, verify
#   read/write/delete permissions, remove stale temporary files, and write
#   the CACHEDIR.TAG marker.
#
#   Exit codes:
#     0 — success (or caching is disabled)
#     1 — directory cannot be created or permissions are insufficient
#
#   When CONTAINER_CACHE is empty (caching disabled), this function is a
#   no-op that logs a warning and returns 0.
cache_init() {
  cache_resolve_dir

  if [[ -z "${CONTAINER_CACHE:-}" ]]; then
    log_warn "CONTAINER_CACHE has been unset.  Release caching is disabled."
    return 0
  fi

  log "Using CONTAINER_CACHE: ${CONTAINER_CACHE}"

  # Create the cache directory if it doesn't already exist.
  if ! mkdir -p "${CONTAINER_CACHE}" 2> /dev/null; then
    log_error "Failed to create CONTAINER_CACHE directory: ${CONTAINER_CACHE}"
    return 1
  fi

  # Verify read, write, and delete permissions on the cache directory.
  local test_file="${CONTAINER_CACHE}/.cache-permissions-test.txt"
  log_debug "Testing permissions on cache directory: ${CONTAINER_CACHE}"
  if ! touch "${test_file}" 2> /dev/null; then
    log_error "Cache directory write test failed: ${CONTAINER_CACHE}"
    return 1
  fi
  if ! cat "${test_file}" > /dev/null 2>&1; then
    log_error "Cache directory read test failed: ${CONTAINER_CACHE}"
    rm -f "${test_file}" 2> /dev/null
    return 1
  fi
  if ! rm -f "${test_file}" 2> /dev/null; then
    log_error "Cache directory delete test failed: ${CONTAINER_CACHE}"
    return 1
  fi
  log_debug "Cache directory permissions OK."

  # Remove stale temporary files from a prior interrupted run.
  cache_cleanup_stale

  # Write the CACHEDIR.TAG marker file.
  cache_write_tag

  return 0
}

# cache_write_tag
#   Write a CACHEDIR.TAG marker file into the cache directory.
#   See https://bford.info/cachedir/ for the specification.
cache_write_tag() {
  local tag_file="${CONTAINER_CACHE}/CACHEDIR.TAG"
  local checksum
  checksum=$(printf ".IsCacheDirectory" | md5sum | cut -d ' ' -f 1)
  printf "Signature: %s\n" "${checksum}" > "${tag_file}"
  {
    printf "# This file is a cache directory tag created by the felddy/foundryvtt container\n"
    printf "# https://github.com/felddy/foundryvtt-docker\n"
    printf "# For information about cache directory tags see https://bford.info/cachedir/\n"
  } >> "${tag_file}"
}

# cache_cleanup_stale
#   Remove stale temporary files left behind by a prior interrupted run.
#   - downloading.zip: partial download from a crash or kill mid-transfer
#   - backoff_state.json.tmp: atomic-write temp file from a crash during backoff
#   Safe to call when no stale files exist (no-op).
cache_cleanup_stale() {
  local stale_downloading="${CONTAINER_CACHE}/downloading.zip"
  local stale_backoff_tmp="${CONTAINER_CACHE}/backoff_state.json.tmp"

  if [[ -f "${stale_downloading}" ]]; then
    log_warn "Removing stale download file: ${stale_downloading}"
    rm -f "${stale_downloading}"
  fi
  if [[ -f "${stale_backoff_tmp}" ]]; then
    log_warn "Removing stale backoff temp file: ${stale_backoff_tmp}"
    rm -f "${stale_backoff_tmp}"
  fi
}

# cache_prune
#   Keep only the CONTAINER_CACHE_SIZE most recent release archives in the
#   cache directory.  Archives are sorted by version number (sort -V).
#
#   When CONTAINER_CACHE_SIZE is unset, all archives are preserved (no-op).
#   When CONTAINER_CACHE is empty (caching disabled), this is a no-op.
#
#   Exit codes:
#     0 — success
#     1 — CONTAINER_CACHE_SIZE is set but not a positive integer
cache_prune() {
  if [[ -z "${CONTAINER_CACHE:-}" ]]; then
    return 0
  fi

  if [[ -z "${CONTAINER_CACHE_SIZE:-}" ]]; then
    log_debug "CONTAINER_CACHE_SIZE is not set. Skipping cache cleanup."
    return 0
  fi

  if ! [[ "${CONTAINER_CACHE_SIZE}" -gt 0 ]] 2> /dev/null; then
    log_error "If set, CONTAINER_CACHE_SIZE must be 1 or greater.  Found: ${CONTAINER_CACHE_SIZE}"
    return 1
  fi

  log "Preserving release archive file in cache."
  log "Cleaning up cache directory: ${CONTAINER_CACHE}"
  log "Keeping ${CONTAINER_CACHE_SIZE} latest versions."

  local cache_files_removed_count=0

  # Store the list of cache files to remove (those beyond the keep limit).
  local file_list
  file_list=$(find "${CONTAINER_CACHE}" -maxdepth 1 -name 'foundryvtt-*.zip' \
    | sort -Vr \
    | awk -v keep="${CONTAINER_CACHE_SIZE}" 'NR > keep')

  if [[ -n "${file_list}" ]]; then
    for file in ${file_list}; do
      log_warn "Removing: ${file}"
      rm -f "${file}"
      cache_files_removed_count=$((cache_files_removed_count + 1))
    done
    log "Completed cache cleanup. Removed ${cache_files_removed_count} files."
  else
    log "No cache cleanup was necessary."
  fi

  return 0
}
