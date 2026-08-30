#!/usr/bin/env bash
set -euo pipefail

APP_DIR="/Users/joshuahamer/Documents/python_projects/EdgeIQ"
HOST="127.0.0.1"
IFS=" " read -r -a PORTS <<< "${EDGEIQ_PORTS:-8007 8000 8001 8002 8003 8004 8005 8006 8008 8009 8010 8011 8012 8013}"

cd "$APP_DIR"

pick_python() {
  if [[ -n "${PYTHON_BIN:-}" ]] && "$PYTHON_BIN" -c "import uvicorn" >/dev/null 2>&1; then
    echo "$PYTHON_BIN"
    return 0
  fi
  for candidate in \
    "$APP_DIR/venv/bin/python" \
    "/Library/Frameworks/Python.framework/Versions/3.13/bin/python3" \
    "/opt/homebrew/bin/python3" \
    "/usr/local/bin/python3" \
    "/usr/bin/python3"
  do
    if [[ -x "$candidate" ]] && "$candidate" -c "import uvicorn" >/dev/null 2>&1; then
      echo "$candidate"
      return 0
    fi
  done
  return 1
}

health_ok() {
  local port="$1"
  /usr/bin/curl -fsS "http://${HOST}:${port}/api/health" >/dev/null 2>&1
}

current_app_ok() {
  local port="$1"
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
        echo "Stopping outdated EdgeIQ server on ${HOST}:${port} (PID ${pid})"
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
      echo "$port:running"
      return 0
    fi
  done

  for port in "${PORTS[@]}"; do
    if ! /usr/sbin/lsof -nP -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1; then
      echo "$port:free"
      return 0
    fi
  done

  return 1
}

PYTHON_BIN="$(pick_python)" || {
  echo "No Python runtime with uvicorn was found."
  echo "From the project folder, run: pip install -r requirements.txt"
  read -r -p "Press Return to close..."
  exit 1
}
if "$PYTHON_BIN" -c "import alembic" >/dev/null 2>&1; then
  echo "Applying EdgeIQ database migrations..."
  "$PYTHON_BIN" -m alembic upgrade head
fi
REQUIRED_UI_VERSION="$(
  "$PYTHON_BIN" -c 'from web.app import STATIC_ASSET_VERSION; print(STATIC_ASSET_VERSION)'
)"

stop_stale_edgeiq_servers
PORT_STATE="$(find_port)" || {
  echo "EdgeIQ could not find a free local port from 8000-8013."
  read -r -p "Press Return to close..."
  exit 1
}
PORT="${PORT_STATE%%:*}"
STATE="${PORT_STATE##*:}"
URL="http://${HOST}:${PORT}"

if [[ "$STATE" == "running" ]]; then
  echo "EdgeIQ is already running at ${URL}"
  /usr/bin/open "$URL"
  exit 0
fi

echo "Starting EdgeIQ at ${URL}"
echo "Keep this Terminal window open while using the app."

(
  for _ in {1..40}; do
    if health_ok "$PORT"; then
      /usr/bin/open "$URL"
      exit 0
    fi
    /bin/sleep 0.5
  done
) &

exec "$PYTHON_BIN" -m uvicorn web.app:app --host "$HOST" --port "$PORT"
