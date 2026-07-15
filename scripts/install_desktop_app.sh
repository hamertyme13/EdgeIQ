#!/usr/bin/env bash
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_BUNDLE="${1:-$HOME/Desktop/EdgeIQ.app}"
ICON_PATH="$APP_DIR/assets/EdgeIQ.icns"
LAUNCHER="$APP_DIR/scripts/launch_edgeiq.sh"
PLIST="$APP_BUNDLE/Contents/Info.plist"
MACOS_DIR="$APP_BUNDLE/Contents/MacOS"
RESOURCES_DIR="$APP_BUNDLE/Contents/Resources"
APP_EXECUTABLE="$MACOS_DIR/EdgeIQ"

cd "$APP_DIR"

if [[ ! -x "$LAUNCHER" ]]; then
  /bin/chmod +x "$LAUNCHER"
fi

"${PYTHON_BIN:-python3}" "$APP_DIR/scripts/generate_desktop_icon.py" >/dev/null

/bin/rm -rf "$APP_BUNDLE"
/bin/mkdir -p "$MACOS_DIR" "$RESOURCES_DIR"

/bin/cat >"$APP_EXECUTABLE" <<LAUNCHER_SCRIPT
#!/usr/bin/env bash
/usr/bin/osascript <<'APPLESCRIPT'
tell application "Terminal"
	activate
	do script quoted form of "$LAUNCHER"
end tell
APPLESCRIPT
LAUNCHER_SCRIPT
/bin/chmod +x "$APP_EXECUTABLE"

/bin/cat >"$PLIST" <<PLIST_XML
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key>
  <string>EdgeIQ</string>
  <key>CFBundleDisplayName</key>
  <string>EdgeIQ</string>
  <key>CFBundleIdentifier</key>
  <string>com.edgeiq.desktop</string>
  <key>CFBundleExecutable</key>
  <string>EdgeIQ</string>
  <key>CFBundlePackageType</key>
  <string>APPL</string>
  <key>CFBundleShortVersionString</key>
  <string>2.0.1</string>
  <key>CFBundleVersion</key>
  <string>20260714.2</string>
  <key>CFBundleIconFile</key>
  <string>EdgeIQ</string>
  <key>CFBundleIconName</key>
  <string>EdgeIQ</string>
  <key>LSMinimumSystemVersion</key>
  <string>12.0</string>
  <key>NSHighResolutionCapable</key>
  <true/>
</dict>
</plist>
PLIST_XML

/bin/cp "$ICON_PATH" "$APP_BUNDLE/Contents/Resources/EdgeIQ.icns"
/usr/bin/plutil -lint "$PLIST" >/dev/null

/usr/bin/touch "$APP_BUNDLE"

echo "Installed EdgeIQ desktop app at $APP_BUNDLE"
echo "Launch it by double-clicking the app. EdgeIQ will open in your browser."
