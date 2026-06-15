#!/bin/bash

# Define terminal colors for use in logger functions
BLUE="\e[34m"
GREEN="\e[32m"
RED="\e[31m"
RESET="\e[0m"
YELLOW="\e[33m"

# Log level numeric mapping (higher = more verbose):
#   quiet=0  error=1  warn=2  info=3  debug=4
# Resolve CONTAINER_LOG_LEVEL with backward compatibility for CONTAINER_VERBOSE.
# CONTAINER_LOG_LEVEL takes precedence; if unset, CONTAINER_VERBOSE non-empty
# implies "debug"; otherwise default is "info".
_resolve_log_level() {
  local level="${CONTAINER_LOG_LEVEL:-}"
  if [[ -z "$level" ]]; then
    if [[ "${CONTAINER_VERBOSE:-}" ]]; then
      level="debug"
    else
      level="info"
    fi
  fi
  case "${level,,}" in
    debug) echo 4 ;;
    info)  echo 3 ;;
    warn)  echo 2 ;;
    error) echo 1 ;;
    quiet) echo 0 ;;
    *)     echo 3 ;;  # unknown → default to info
  esac
}
_LOG_LEVEL_NUM=$(_resolve_log_level)

# Mimic the winston logging used in logging.ts — all output to stderr
log_debug() {
  if [[ $_LOG_LEVEL_NUM -ge 4 ]]; then
    echo -e "${LOG_NAME} | $(date +%Y-%m-%d\ %H:%M:%S) | [${BLUE}debug${RESET}] $*" >&2
  fi
}

log() {
  if [[ $_LOG_LEVEL_NUM -ge 3 ]]; then
    echo -e "${LOG_NAME} | $(date +%Y-%m-%d\ %H:%M:%S) | [${GREEN}info${RESET}] $*" >&2
  fi
}

log_warn() {
  if [[ $_LOG_LEVEL_NUM -ge 2 ]]; then
    echo -e "${LOG_NAME} | $(date +%Y-%m-%d\ %H:%M:%S) | [${YELLOW}warn${RESET}] $*" >&2
  fi
}

log_error() {
  if [[ $_LOG_LEVEL_NUM -ge 1 ]]; then
    echo -e "${LOG_NAME} | $(date +%Y-%m-%d\ %H:%M:%S) | [${RED}error${RESET}] $*" >&2
  fi
}
