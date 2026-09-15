#!/bin/sh

set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)
PROJECT_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd -P)
SERVICE_EXECUTABLE="$PROJECT_ROOT/.venv/bin/ase-console"
DEFAULT_STATE_BASE=${XDG_STATE_HOME:-"${HOME:?HOME is required}/.local/state"}
SERVICE_STATE_DIR=${ASE_SERVICE_STATE_DIR:-"$DEFAULT_STATE_BASE/ai-software-engineer"}
DEFAULT_CONFIG_BASE=${XDG_CONFIG_HOME:-"${HOME:?HOME is required}/.config"}
CONFIG_FILE=${ASE_CONFIG:-"$DEFAULT_CONFIG_BASE/ai-software-engineer/config.json"}
CONFIG_DIRECTORY=$(dirname -- "$CONFIG_FILE")
RUNTIME_ENV_FILE="$CONFIG_DIRECTORY/runtime.env"
PID_FILE="$SERVICE_STATE_DIR/ase-console.pid"
LOG_FILE="$SERVICE_STATE_DIR/ase-console.log"

usage() {
  echo "Usage: $0 {start|stop|restart|status|logs}"
}

require_safe_state_dir() {
  case "$SERVICE_STATE_DIR" in
    /*) ;;
    *)
      echo "error: ASE_SERVICE_STATE_DIR must be an absolute path" >&2
      exit 2
      ;;
  esac
  if [ "$SERVICE_STATE_DIR" = "/" ] || [ -L "$SERVICE_STATE_DIR" ]; then
    echo "error: unsafe service state directory" >&2
    exit 2
  fi
  mkdir -p "$SERVICE_STATE_DIR"
}

read_pid() {
  if [ -L "$PID_FILE" ]; then
    echo "error: refusing symlink PID file: $PID_FILE" >&2
    exit 2
  fi
  [ -f "$PID_FILE" ] || return 1
  pid=$(sed -n '1p' "$PID_FILE")
  case "$pid" in
    ''|*[!0-9]*) return 1 ;;
  esac
  printf '%s\n' "$pid"
}

read_managed_executable() {
  [ -f "$PID_FILE" ] || return 1
  managed_executable=$(sed -n '2p' "$PID_FILE")
  case "$managed_executable" in
    /*/.venv/bin/ase-console) printf '%s\n' "$managed_executable" ;;
    *) return 1 ;;
  esac
}

load_runtime_environment() {
  if [ ! -e "$RUNTIME_ENV_FILE" ]; then
    return 0
  fi
  if [ -L "$RUNTIME_ENV_FILE" ] || [ ! -f "$RUNTIME_ENV_FILE" ]; then
    echo "error: runtime environment is not a regular file: $RUNTIME_ENV_FILE" >&2
    exit 2
  fi
  set -a
  # The file is written by the typed Web Console store using canonical POSIX quoting.
  . "$RUNTIME_ENV_FILE"
  set +a
}

process_exists() {
  candidate_pid=$1
  kill -0 "$candidate_pid" 2>/dev/null || return 1
}

process_matches_executable() {
  candidate_pid=$1
  candidate_executable=$2
  process_exists "$candidate_pid" || return 1
  command_line=$(ps -p "$candidate_pid" -o command= 2>/dev/null || true)
  case "$command_line" in
    *"$candidate_executable"*) return 0 ;;
    *) return 1 ;;
  esac
}

is_our_process() {
  process_matches_executable "$1" "$SERVICE_EXECUTABLE"
}

is_managed_process() {
  candidate_pid=$1
  managed_executable=$(read_managed_executable) || return 1
  process_matches_executable "$candidate_pid" "$managed_executable"
}

start_service() {
  require_safe_state_dir
  if current_pid=$(read_pid 2>/dev/null) && process_exists "$current_pid"; then
    if is_our_process "$current_pid"; then
      echo "ase-console is already running (pid $current_pid)"
      return 0
    fi
    if is_managed_process "$current_pid"; then
      managed_executable=$(read_managed_executable)
      echo "ase-console is already running from $managed_executable (pid $current_pid)"
      return 0
    fi
    echo "error: PID file does not identify a managed ase-console; no process replaced" >&2
    exit 1
  fi
  if [ ! -x "$SERVICE_EXECUTABLE" ]; then
    echo "error: $SERVICE_EXECUTABLE is missing; run 'uv sync' first" >&2
    exit 2
  fi
  load_runtime_environment
  export ASE_CONFIG="$CONFIG_FILE"
  : >>"$LOG_FILE"
  nohup "$SERVICE_EXECUTABLE" >>"$LOG_FILE" 2>&1 </dev/null &
  started_pid=$!
  {
    printf '%s\n' "$started_pid"
    printf '%s\n' "$SERVICE_EXECUTABLE"
  } >"$PID_FILE"
  sleep 1
  if ! is_our_process "$started_pid"; then
    rm -f "$PID_FILE"
    echo "error: ase-console exited during startup; inspect $LOG_FILE" >&2
    tail -n 30 "$LOG_FILE" >&2 || true
    exit 1
  fi
  echo "ase-console started (pid $started_pid)"
  echo "log: $LOG_FILE"
}

stop_service() {
  require_safe_state_dir
  if ! current_pid=$(read_pid 2>/dev/null); then
    echo "ase-console is not running"
    return 0
  fi
  if ! process_exists "$current_pid"; then
    rm -f "$PID_FILE"
    echo "ase-console is not running (removed stale PID $current_pid)"
    return 0
  fi
  if ! is_our_process "$current_pid" && ! is_managed_process "$current_pid"; then
    echo "error: PID file does not identify this project's ase-console; no signal sent" >&2
    echo "remove the stale PID file after inspecting it: $PID_FILE" >&2
    exit 1
  fi
  if ! is_our_process "$current_pid"; then
    managed_executable=$(read_managed_executable)
    echo "stopping managed ase-console from $managed_executable"
  fi
  kill -TERM "$current_pid"
  remaining=80
  while kill -0 "$current_pid" 2>/dev/null && [ "$remaining" -gt 0 ]; do
    sleep 0.25
    remaining=$((remaining - 1))
  done
  if kill -0 "$current_pid" 2>/dev/null; then
    echo "error: ase-console did not stop within 20 seconds; process left intact" >&2
    exit 1
  fi
  rm -f "$PID_FILE"
  echo "ase-console stopped"
}

status_service() {
  require_safe_state_dir
  if current_pid=$(read_pid 2>/dev/null); then
    if is_our_process "$current_pid"; then
      echo "ase-console is running (pid $current_pid)"
      echo "log: $LOG_FILE"
      return 0
    fi
    if is_managed_process "$current_pid"; then
      managed_executable=$(read_managed_executable)
      echo "ase-console is running from $managed_executable (pid $current_pid)"
      echo "log: $LOG_FILE"
      return 0
    fi
  fi
  echo "ase-console is not running"
  return 1
}

case "${1:-}" in
  start) start_service ;;
  stop) stop_service ;;
  restart)
    stop_service
    start_service
    ;;
  status) status_service ;;
  logs)
    require_safe_state_dir
    if [ ! -f "$LOG_FILE" ]; then
      echo "ase-console has not written a log yet: $LOG_FILE" >&2
      exit 1
    fi
    tail -n 100 -f "$LOG_FILE"
    ;;
  *)
    usage >&2
    exit 2
    ;;
esac
