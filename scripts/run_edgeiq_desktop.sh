#!/usr/bin/env bash
set -euo pipefail

APP_DIR="/Users/joshuahamer/Documents/python_projects/EdgeIQ"
HOST="127.0.0.1"
REQUIRED_UI_VERSION="20260716-desktop-final-stats"
IFS=" " read -r -a PORTS <<< "${EDGEIQ_PORTS:-8007 8000 8001 8002 8003 8004 8005}"

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

PORT_STATE="$(find_port)" || {
  echo "Ports 8007 and 8000-8005 are already in use."
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
