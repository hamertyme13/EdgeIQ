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
/bin/mkdir -p "$(dirname "$PLIST")" "$LOG_DIR"
/bin/cat >"$PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>${LABEL}</string>
  <key>ProgramArguments</key><array>
    <string>${PYTHON_BIN}</string>
    <string>${APP_DIR}/scripts/run_scheduled_maintenance.py</string>
  </array>
  <key>WorkingDirectory</key><string>${APP_DIR}</string>
  <key>StartInterval</key><integer>900</integer>
  <key>StandardOutPath</key><string>${LOG_DIR}/scheduler.log</string>
  <key>StandardErrorPath</key><string>${LOG_DIR}/scheduler-error.log</string>
</dict></plist>
PLIST
/usr/bin/plutil -lint "$PLIST" >/dev/null
/bin/launchctl bootout "gui/$(id -u)/${LABEL}" >/dev/null 2>&1 || true
for attempt in 1 2 3; do
  if /bin/launchctl bootstrap "gui/$(id -u)" "$PLIST"; then
    break
  fi
  if [[ "$attempt" -eq 3 ]]; then
    echo "EdgeIQ scheduler could not be registered with launchd." >&2
    exit 1
  fi
  /bin/sleep 2
done
echo "Installed EdgeIQ background scheduler at $PLIST"
