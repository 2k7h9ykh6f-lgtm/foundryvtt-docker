#!/bin/bash

# Unified logging library for foundryvtt-docker
# Supports FOUNDRY_LOG_LEVEL environment variable with levels: error, warn, info, debug
# Backward compatible with CONTAINER_VERBOSE (treated as debug level)

set -o nounset
set -o errexit
set -o pipefail

# Define terminal colors for use in logger functions
BLUE="\e[34m"
GREEN="\e[32m"
RED="\e[31m"
RESET="\e[0m"
YELLOW="\e[33m"

# Determine effective log level
# Priority: FOUNDRY_LOG_LEVEL > CONTAINER_VERBOSE > default (info)
_log_level="${FOUNDRY_LOG_LEVEL:-}"
if [[ -z "${_log_level}" && "${CONTAINER_VERBOSE:-}" ]]; then
  _log_level="debug"
fi
_log_level="${_log_level:-info}"
_log_level="${_log_level,,}" # lowercase

# Map level names to numeric values for comparison
_log_level_to_num() {
  case "${1}" in
    error) echo 0 ;;
    warn)  echo 1 ;;
    info)  echo 2 ;;
    debug) echo 3 ;;
    *)     echo 2 ;; # default to info
  esac
}

_current_level_num=$(_log_level_to_num "${_log_level}")

# log_debug - Output debug level messages (only if log level is debug)
log_debug() {
  if [[ ${_current_level_num} -ge 3 ]]; then
    echo -e "${LOG_NAME} | $(date +%Y-%m-%d\ %H:%M:%S) | [${BLUE}debug${RESET}] $*"
  fi
}

# log_info - Output info level messages (if log level is info or higher)
# This is an alias for log() for consistency
log_info() {
  if [[ ${_current_level_num} -ge 2 ]]; then
    echo -e "${LOG_NAME} | $(date +%Y-%m-%d\ %H:%M:%S) | [${GREEN}info${RESET}] $*"
  fi
}

# log - Output info level messages (backward compatible alias for log_info)
log() {
  log_info "$@"
}

# log_warn - Output warning level messages (if log level is warn or higher)
log_warn() {
  if [[ ${_current_level_num} -ge 1 ]]; then
    echo -e "${LOG_NAME} | $(date +%Y-%m-%d\ %H:%M:%S) | [${YELLOW}warn${RESET}] $*"
  fi
}

# log_error - Output error level messages (always output unless level is error)
log_error() {
  if [[ ${_current_level_num} -ge 0 ]]; then
    echo -e "${LOG_NAME} | $(date +%Y-%m-%d\ %H:%M:%S) | [${RED}error${RESET}] $*"
  fi
}
