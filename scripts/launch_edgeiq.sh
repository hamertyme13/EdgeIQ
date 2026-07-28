#!/usr/bin/env bash
set -euo pipefail

APP_DIR="/Users/joshuahamer/Documents/python_projects/EdgeIQ"
LOG_FILE="/tmp/edgeiq.log"
PYTHON_BIN="${PYTHON_BIN:-}"
HOST="127.0.0.1"
IFS=" " read -r -a PORTS <<< "${EDGEIQ_PORTS:-8007 8000 8001 8002 8003 8004 8005 8006 8008 8009 8010 8011 8012 8013}"

cd "$APP_DIR"

if [[ -z "$PYTHON_BIN" ]]; then
  for candidate in \
    "$APP_DIR/venv/bin/python" \
    "/Library/Frameworks/Python.framework/Versions/3.13/bin/python3" \
    "/opt/homebrew/bin/python3" \
    "/usr/local/bin/python3" \
    "/usr/bin/python3"
  do
    if [[ -x "$candidate" ]] && "$candidate" -c "import uvicorn" >/dev/null 2>&1; then
      PYTHON_BIN="$candidate"
      break
    fi
  done
fi

if [[ -z "$PYTHON_BIN" ]]; then
  /usr/bin/osascript -e 'display alert "EdgeIQ could not launch" message "No Python runtime with uvicorn was found. Install requirements or run pip install -r requirements.txt."'
  exit 1
fi
REQUIRED_UI_VERSION="$(
  "$PYTHON_BIN" -c 'from web.app import STATIC_ASSET_VERSION; print(STATIC_ASSET_VERSION)'
)"

health_ok() {
  local port="$1"
  /usr/bin/curl -fsS "http://${HOST}:${port}/api/health" >/dev/null 2>&1
}

current_app_ok() {
  local port="$1"
  if ! health_ok "$port"; then
    return 1
  fi
  /usr/bin/curl -fsS "http://${HOST}:${port}/api/version" 2>/dev/null | /usr/bin/grep -q "\"ui_asset_version\":\"${REQUIRED_UI_VERSION}\""
}

edgeiq_server() {
  local port="$1"
  /usr/bin/curl -fsS "http://${HOST}:${port}/api/version" 2>/dev/null |
    /usr/bin/grep -q '"app":"EdgeIQ Web"'
}

stop_stale_edgeiq_servers() {
  local port pid
  for port in "${PORTS[@]}"; do
    if edgeiq_server "$port" && ! current_app_ok "$port"; then
      pid="$(/usr/sbin/lsof -nP -t -iTCP:"$port" -sTCP:LISTEN 2>/dev/null || true)"
      if [[ -n "$pid" ]]; then
        echo "Stopping outdated EdgeIQ server on ${HOST}:${port} (PID ${pid})" >>"$LOG_FILE"
        /bin/kill "$pid" >/dev/null 2>&1 || true
      fi
    fi
  done

  for _ in {1..20}; do
    local stale_running=0
    for port in "${PORTS[@]}"; do
      if edgeiq_server "$port" && ! current_app_ok "$port"; then
        stale_running=1
        break
      fi
    done
    [[ "$stale_running" -eq 0 ]] && return 0
    /bin/sleep 0.1
  done
}

find_port() {
  for port in "${PORTS[@]}"; do
    if current_app_ok "$port"; then
      echo "$port"
      return 0
    fi
  done

  for port in "${PORTS[@]}"; do
    if ! /usr/sbin/lsof -nP -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1; then
      echo "$port"
      return 0
    fi
  done

  return 1
}

stop_stale_edgeiq_servers
PORT="$(find_port)"
if [[ -z "${PORT:-}" ]]; then
  /usr/bin/osascript -e 'display alert "EdgeIQ could not launch" message "EdgeIQ could not find a free local port from 8000-8013. Close another local server and try again."'
  exit 1
fi

if ! health_ok "$PORT"; then
  echo "Starting EdgeIQ on ${HOST}:${PORT} at $(date) with ${PYTHON_BIN}" >>"$LOG_FILE"
  /usr/bin/nohup "$PYTHON_BIN" -m uvicorn web.app:app --host "$HOST" --port "$PORT" >>"$LOG_FILE" 2>&1 &

  for _ in {1..30}; do
    if health_ok "$PORT"; then
      break
    fi
    /bin/sleep 0.5
  done
fi

if health_ok "$PORT"; then
  /usr/bin/open "http://${HOST}:${PORT}"
else
  /usr/bin/osascript -e 'display alert "EdgeIQ did not finish launching" message "Check /tmp/edgeiq.log for details."'
  exit 1
fi
