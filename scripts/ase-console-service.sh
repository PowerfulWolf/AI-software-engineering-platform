#!/bin/sh

set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)
SERVICE_SCRIPT="$SCRIPT_DIR/ase-console-service.sh"
PROJECT_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd -P)
SERVICE_EXECUTABLE="$PROJECT_ROOT/.venv/bin/ase-console"
DEFAULT_STATE_BASE=${XDG_STATE_HOME:-"${HOME:?HOME is required}/.local/state"}
SERVICE_STATE_DIR=${ASE_SERVICE_STATE_DIR:-"$DEFAULT_STATE_BASE/ai-software-engineer"}
DEFAULT_CONFIG_BASE=${XDG_CONFIG_HOME:-"${HOME:?HOME is required}/.config"}
CONFIG_FILE=${ASE_CONFIG:-"$DEFAULT_CONFIG_BASE/ai-software-engineer/config.json"}
CONFIG_DIRECTORY=$(dirname -- "$CONFIG_FILE")
RUNTIME_ENV_FILE="$CONFIG_DIRECTORY/runtime.env"
PID_FILE="$SERVICE_STATE_DIR/ase-console.pid"
SUPERVISOR_PID_FILE="$SERVICE_STATE_DIR/ase-console-supervisor.pid"
SUPERVISOR_LOCK_DIR="$SERVICE_STATE_DIR/ase-console-supervisor.lock"
SUPERVISOR_LOCK_OWNER_FILE="$SUPERVISOR_LOCK_DIR/owner"
LOG_FILE="$SERVICE_STATE_DIR/ase-console.log"
APPLY_REQUEST_FILE="$SERVICE_STATE_DIR/configuration-apply.request"
APPLY_STATE_FILE="$SERVICE_STATE_DIR/configuration-apply.json"

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
  for state_path in \
    "$PID_FILE" "$SUPERVISOR_PID_FILE" "$APPLY_REQUEST_FILE" "$APPLY_STATE_FILE"
  do
    if [ -L "$state_path" ]; then
      echo "error: refusing symlink service state file: $state_path" >&2
      exit 2
    fi
  done
  if [ -L "$SUPERVISOR_LOCK_DIR" ] || { [ -e "$SUPERVISOR_LOCK_DIR" ] && [ ! -d "$SUPERVISOR_LOCK_DIR" ]; }; then
    echo "error: refusing unsafe supervisor lock: $SUPERVISOR_LOCK_DIR" >&2
    exit 2
  fi
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

launch_child() {
  # Keep values loaded from runtime.env inside the child-launch subshell. The
  # long-lived supervisor must not retain a secret that a later save removes.
  (
    # This function is also called from an `if` condition, where POSIX shells
    # may suppress `set -e` for the whole function body. Propagate a malformed
    # or unsafe runtime.env explicitly instead of continuing with stale input.
    load_runtime_environment || exit 1
    export ASE_CONFIG="$CONFIG_FILE"
    : >>"$LOG_FILE"
    nohup "$SERVICE_EXECUTABLE" >>"$LOG_FILE" 2>&1 </dev/null &
    child_pid=$!
    {
      printf '%s\n' "$child_pid"
      printf '%s\n' "$SERVICE_EXECUTABLE"
    } >"$PID_FILE"
  )
  started_pid=$(read_pid)
}

read_supervisor_pid() {
  [ -f "$SUPERVISOR_PID_FILE" ] || return 1
  supervisor_pid=$(sed -n '1p' "$SUPERVISOR_PID_FILE")
  supervisor_script=$(sed -n '2p' "$SUPERVISOR_PID_FILE")
  case "$supervisor_pid" in
    ''|*[!0-9]*) return 1 ;;
  esac
  case "$supervisor_script" in
    /*/scripts/ase-console-service.sh) ;;
    *) return 1 ;;
  esac
  [ -f "$supervisor_script" ] && [ ! -L "$supervisor_script" ] || return 1
  printf '%s\n' "$supervisor_pid"
}

is_supervisor_process() {
  candidate_pid=$1
  supervisor_script=$(sed -n '2p' "$SUPERVISOR_PID_FILE")
  process_matches_supervisor "$candidate_pid" "$supervisor_script"
}

process_matches_supervisor() {
  candidate_pid=$1
  supervisor_script=$2
  process_exists "$candidate_pid" || return 1
  command_line=$(ps -p "$candidate_pid" -o command= 2>/dev/null || true)
  python3 - "$supervisor_script" "$command_line" <<'PY'
import shlex
import sys

script = sys.argv[1]
try:
    arguments = shlex.split(sys.argv[2])
except ValueError:
    raise SystemExit(1)
if arguments == [script, "supervise"]:
    raise SystemExit(0)
if len(arguments) == 3 and arguments[0].rsplit("/", 1)[-1] == "sh":
    raise SystemExit(0 if arguments[1:] == [script, "supervise"] else 1)
raise SystemExit(1)
PY
}

start_supervisor() {
  if supervisor_pid=$(read_supervisor_pid 2>/dev/null); then
    if is_supervisor_process "$supervisor_pid"; then
      return 0
    fi
    if process_exists "$supervisor_pid"; then
      echo "error: supervisor PID file does not identify the managed service script" >&2
      return 1
    fi
  fi
  rm -f "$SUPERVISOR_PID_FILE"
  nohup "$SERVICE_SCRIPT" supervise >>"$LOG_FILE" 2>&1 </dev/null &
  launched_supervisor_pid=$!
  remaining=20
  while [ "$remaining" -gt 0 ]; do
    if supervisor_pid=$(read_supervisor_pid 2>/dev/null) && is_supervisor_process "$supervisor_pid"; then
      return 0
    fi
    if ! process_exists "$launched_supervisor_pid"; then
      break
    fi
    sleep 0.05
    remaining=$((remaining - 1))
  done
  echo "error: ase-console supervisor could not acquire ownership" >&2
  return 1
}

stop_supervisor() {
  [ -f "$SUPERVISOR_PID_FILE" ] || return 0
  supervisor_pid=$(read_supervisor_pid 2>/dev/null) || {
    echo "error: invalid supervisor PID record; no signal sent" >&2
    return 1
  }
  if process_exists "$supervisor_pid"; then
    if ! is_supervisor_process "$supervisor_pid"; then
      echo "error: supervisor PID does not identify the managed service script; no signal sent" >&2
      return 1
    fi
    kill -TERM "$supervisor_pid"
    remaining=80
    while kill -0 "$supervisor_pid" 2>/dev/null && [ "$remaining" -gt 0 ]; do
      sleep 0.25
      remaining=$((remaining - 1))
    done
    if kill -0 "$supervisor_pid" 2>/dev/null; then
      echo "error: ase-console supervisor did not stop within 20 seconds" >&2
      return 1
    fi
  fi
  remove_supervisor_record_if_owned "$supervisor_pid"
}

remove_supervisor_record_if_owned() {
  owner_pid=$1
  if [ -f "$SUPERVISOR_PID_FILE" ] && [ ! -L "$SUPERVISOR_PID_FILE" ]; then
    recorded_pid=$(sed -n '1p' "$SUPERVISOR_PID_FILE")
    recorded_script=$(sed -n '2p' "$SUPERVISOR_PID_FILE")
    if [ "$recorded_pid" = "$owner_pid" ] && [ "$recorded_script" = "$SERVICE_SCRIPT" ]; then
      rm -f "$SUPERVISOR_PID_FILE"
    fi
  fi
  if lock_owner_pid=$(read_supervisor_lock_owner 2>/dev/null); then
    lock_owner_script=$(sed -n '2p' "$SUPERVISOR_LOCK_OWNER_FILE")
    if [ "$lock_owner_pid" = "$owner_pid" ] && [ "$lock_owner_script" = "$SERVICE_SCRIPT" ]; then
      rm -f "$SUPERVISOR_LOCK_OWNER_FILE"
      rmdir "$SUPERVISOR_LOCK_DIR" 2>/dev/null || true
    fi
  fi
}

read_supervisor_lock_owner() {
  [ -d "$SUPERVISOR_LOCK_DIR" ] && [ ! -L "$SUPERVISOR_LOCK_DIR" ] || return 1
  [ -f "$SUPERVISOR_LOCK_OWNER_FILE" ] && [ ! -L "$SUPERVISOR_LOCK_OWNER_FILE" ] || return 1
  lock_owner_pid=$(sed -n '1p' "$SUPERVISOR_LOCK_OWNER_FILE")
  lock_owner_script=$(sed -n '2p' "$SUPERVISOR_LOCK_OWNER_FILE")
  case "$lock_owner_pid" in
    ''|*[!0-9]*) return 1 ;;
  esac
  case "$lock_owner_script" in
    /*/scripts/ase-console-service.sh) ;;
    *) return 1 ;;
  esac
  [ -f "$lock_owner_script" ] && [ ! -L "$lock_owner_script" ] || return 1
  printf '%s\n' "$lock_owner_pid"
}

acquire_supervisor_ownership() {
  if mkdir "$SUPERVISOR_LOCK_DIR" 2>/dev/null; then
    umask 077
    if {
      printf '%s\n' "$$"
      printf '%s\n' "$SERVICE_SCRIPT"
    } >"$SUPERVISOR_LOCK_OWNER_FILE"; then
      return 0
    fi
    rm -f "$SUPERVISOR_LOCK_OWNER_FILE"
    rmdir "$SUPERVISOR_LOCK_DIR" 2>/dev/null || true
    return 1
  fi
  # A lock without a complete owner record may be an owner still publishing
  # its claim. Never remove it: an unverifiable lock fails closed.
  lock_owner_pid=$(read_supervisor_lock_owner 2>/dev/null) || return 1
  lock_owner_script=$(sed -n '2p' "$SUPERVISOR_LOCK_OWNER_FILE")
  if process_matches_supervisor "$lock_owner_pid" "$lock_owner_script"; then
    return 1
  fi
  rm -f "$SUPERVISOR_LOCK_OWNER_FILE"
  rmdir "$SUPERVISOR_LOCK_DIR" 2>/dev/null || return 1
  if ! mkdir "$SUPERVISOR_LOCK_DIR" 2>/dev/null; then
    return 1
  fi
  umask 077
  if {
    printf '%s\n' "$$"
    printf '%s\n' "$SERVICE_SCRIPT"
  } >"$SUPERVISOR_LOCK_OWNER_FILE"; then
    return 0
  fi
  rm -f "$SUPERVISOR_LOCK_OWNER_FILE"
  rmdir "$SUPERVISOR_LOCK_DIR" 2>/dev/null || true
  return 1
}

write_apply_state() {
  apply_request_id=$1
  apply_status=$2
  case "$apply_status" in
    SUCCEEDED) apply_summary='Configuration was applied.' ;;
    FAILED) apply_summary='Configuration remains saved but the Console could not be restarted. Use the service script to inspect status and retry safely.' ;;
    *) return 1 ;;
  esac
  umask 077
  temporary_state=$(mktemp "$SERVICE_STATE_DIR/.configuration-apply.XXXXXX")
  printf '{"request_id":"%s","safe_summary":"%s","status":"%s"}\n' \
    "$apply_request_id" "$apply_summary" "$apply_status" >"$temporary_state"
  mv -f "$temporary_state" "$APPLY_STATE_FILE"
}

read_apply_state_status() {
  expected_request_id=$1
  [ -f "$APPLY_STATE_FILE" ] && [ ! -L "$APPLY_STATE_FILE" ] || return 1
  apply_state_body=$(cat "$APPLY_STATE_FILE")
  pending_summary='Configuration apply is in progress.'
  succeeded_summary='Configuration was applied.'
  failed_summary='Configuration remains saved but the Console could not be restarted. Use the service script to inspect status and retry safely.'
  case "$apply_state_body" in
    "{\"request_id\":\"$expected_request_id\",\"safe_summary\":\"$pending_summary\",\"status\":\"PENDING\"}"|"{\"request_id\": \"$expected_request_id\", \"safe_summary\": \"$pending_summary\", \"status\": \"PENDING\"}")
      printf '%s\n' PENDING
      ;;
    "{\"request_id\":\"$expected_request_id\",\"safe_summary\":\"$succeeded_summary\",\"status\":\"SUCCEEDED\"}"|"{\"request_id\": \"$expected_request_id\", \"safe_summary\": \"$succeeded_summary\", \"status\": \"SUCCEEDED\"}")
      printf '%s\n' SUCCEEDED
      ;;
    "{\"request_id\":\"$expected_request_id\",\"safe_summary\":\"$failed_summary\",\"status\":\"FAILED\"}"|"{\"request_id\": \"$expected_request_id\", \"safe_summary\": \"$failed_summary\", \"status\": \"FAILED\"}")
      printf '%s\n' FAILED
      ;;
    *) return 1 ;;
  esac
}

stop_child_for_apply() {
  current_pid=$(read_pid 2>/dev/null) || return 1
  if ! is_our_process "$current_pid" && ! is_managed_process "$current_pid"; then
    return 1
  fi
  kill -TERM "$current_pid"
  remaining=80
  while kill -0 "$current_pid" 2>/dev/null && [ "$remaining" -gt 0 ]; do
    sleep 0.25
    remaining=$((remaining - 1))
  done
  if kill -0 "$current_pid" 2>/dev/null; then
    return 1
  fi
  rm -f "$PID_FILE"
}

supervise_service() {
  require_safe_state_dir
  trap 'exit 0' TERM INT
  trap 'supervisor_status=$?; trap - EXIT; remove_supervisor_record_if_owned "$$"; exit "$supervisor_status"' EXIT
  if ! acquire_supervisor_ownership; then
    echo "error: another ase-console supervisor owns the service state" >&2
    exit 1
  fi
  {
    printf '%s\n' "$$"
    printf '%s\n' "$SERVICE_SCRIPT"
  } >"$SUPERVISOR_PID_FILE"
  if [ ! -e "$APPLY_REQUEST_FILE" ] && [ -f "$APPLY_STATE_FILE" ] && [ ! -L "$APPLY_STATE_FILE" ]; then
    pending_request_id=$(sed -n \
      -e 's/^{"request_id":"\(configuration_apply_[0-9a-f]\{32\}\)","safe_summary":"Configuration apply is in progress.","status":"PENDING"}$/\1/p' \
      -e 's/^{"request_id": "\(configuration_apply_[0-9a-f]\{32\}\)", "safe_summary": "Configuration apply is in progress.", "status": "PENDING"}$/\1/p' \
      "$APPLY_STATE_FILE")
    if [ -n "$pending_request_id" ] && \
      [ "$(read_apply_state_status "$pending_request_id" 2>/dev/null)" = "PENDING" ]; then
      write_apply_state "$pending_request_id" FAILED
    fi
  fi
  while :; do
    if [ -f "$APPLY_REQUEST_FILE" ] && [ ! -L "$APPLY_REQUEST_FILE" ]; then
      apply_request_id=$(sed -n '1p' "$APPLY_REQUEST_FILE")
      apply_suffix=${apply_request_id#configuration_apply_}
      if [ "$apply_request_id" = "configuration_apply_$apply_suffix" ] && \
        [ "${#apply_suffix}" -eq 32 ]; then
        case "$apply_suffix" in
          *[!0-9a-f]*) rm -f "$APPLY_REQUEST_FILE" ;;
          *)
            apply_state_status=$(read_apply_state_status "$apply_request_id" 2>/dev/null) || {
              sleep 0.25
              continue
            }
            case "$apply_state_status" in
              SUCCEEDED|FAILED)
                rm -f "$APPLY_REQUEST_FILE"
                sleep 0.25
                continue
                ;;
              PENDING) rm -f "$APPLY_REQUEST_FILE" ;;
            esac
            if stop_child_for_apply; then
              if launch_child; then
                sleep 1
              fi
              if [ "${started_pid:-}" ] && is_our_process "$started_pid"; then
                write_apply_state "$apply_request_id" SUCCEEDED
              else
                rm -f "$PID_FILE"
                write_apply_state "$apply_request_id" FAILED
              fi
            else
              write_apply_state "$apply_request_id" FAILED
            fi
            ;;
        esac
      else
        rm -f "$APPLY_REQUEST_FILE"
      fi
    fi
    sleep 0.25
  done
}

start_service() {
  require_safe_state_dir
  if current_pid=$(read_pid 2>/dev/null) && process_exists "$current_pid"; then
    if is_our_process "$current_pid"; then
      start_supervisor
      echo "ase-console is already running (pid $current_pid)"
      return 0
    fi
    if is_managed_process "$current_pid"; then
      start_supervisor
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
  launch_child
  sleep 1
  if ! is_our_process "$started_pid"; then
    rm -f "$PID_FILE"
    echo "error: ase-console exited during startup; inspect $LOG_FILE" >&2
    tail -n 30 "$LOG_FILE" >&2 || true
    exit 1
  fi
  if ! start_supervisor; then
    stop_child_for_apply || true
    echo "error: ase-console supervisor could not be started safely" >&2
    exit 1
  fi
  echo "ase-console started (pid $started_pid)"
  echo "log: $LOG_FILE"
}

stop_service() {
  require_safe_state_dir
  if ! current_pid=$(read_pid 2>/dev/null); then
    stop_supervisor
    echo "ase-console is not running"
    return 0
  fi
  if ! process_exists "$current_pid"; then
    rm -f "$PID_FILE"
    stop_supervisor
    echo "ase-console is not running (removed stale PID $current_pid)"
    return 0
  fi
  if ! is_our_process "$current_pid" && ! is_managed_process "$current_pid"; then
    echo "error: PID file does not identify this project's ase-console; no signal sent" >&2
    echo "remove the stale PID file after inspecting it: $PID_FILE" >&2
    exit 1
  fi
  stop_supervisor
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
  supervise) supervise_service ;;
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
