#!/usr/bin/env bash
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LABEL="com.edgeiq.runtime-reliability"
PLIST="$HOME/Library/LaunchAgents/${LABEL}.plist"
LOG_DIR="$HOME/Library/Logs/EdgeIQ"
PYTHON_BIN="${PYTHON_BIN:-}"
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
  echo "No Python runtime with EdgeIQ dependencies was found." >&2
  exit 1
fi
MAINTENANCE_COMMAND="cd '$APP_DIR' && '$PYTHON_BIN' '$APP_DIR/scripts/run_scheduled_maintenance.py' >> '$LOG_DIR/scheduler.log' 2>> '$LOG_DIR/scheduler-error.log'; exit"
MAINTENANCE_XML="${MAINTENANCE_COMMAND//&/&amp;}"

/bin/mkdir -p "$(dirname "$PLIST")" "$LOG_DIR"
/bin/cat >"$PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>${LABEL}</string>
  <key>ProgramArguments</key><array>
    <string>/usr/bin/osascript</string><string>-e</string>
    <string>tell application "Terminal" to do script "${MAINTENANCE_XML}"</string>
  </array>
  <key>StartInterval</key><integer>900</integer>
  <key>RunAtLoad</key><true/>
  <key>StandardOutPath</key><string>${LOG_DIR}/scheduler.log</string>
  <key>StandardErrorPath</key><string>${LOG_DIR}/scheduler-error.log</string>
</dict></plist>
PLIST
/usr/bin/plutil -lint "$PLIST" >/dev/null
/bin/launchctl bootout "gui/$(id -u)/${LABEL}" >/dev/null 2>&1 || true
/bin/launchctl bootstrap "gui/$(id -u)" "$PLIST"
echo "Installed EdgeIQ background scheduler at $PLIST"
