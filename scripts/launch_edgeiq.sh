#!/usr/bin/env bash
set -euo pipefail

APP_DIR="/Users/joshuahamer/Documents/python_projects/EdgeIQ"
LOG_FILE="/tmp/edgeiq.log"
PYTHON_BIN="${PYTHON_BIN:-}"
HOST="127.0.0.1"
REQUIRED_UI_VERSION="20260714-pro-dashboard"
IFS=" " read -r -a PORTS <<< "${EDGEIQ_PORTS:-8000 8001 8002 8003 8004 8005}"

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

PORT="$(find_port)"
if [[ -z "${PORT:-}" ]]; then
  /usr/bin/osascript -e 'display alert "EdgeIQ could not launch" message "Ports 8000-8005 are already in use. Close another local server and try again."'
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
