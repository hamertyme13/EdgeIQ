#!/usr/bin/env bash
set -euo pipefail

APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-}"

cd "$APP_DIR"

python_is_ready() {
  local candidate="$1"
  [[ -x "$candidate" ]] && "$candidate" -c "import alembic, sqlalchemy" >/dev/null 2>&1
}

if [[ -n "$PYTHON_BIN" ]] && ! python_is_ready "$PYTHON_BIN"; then
  echo "The configured PYTHON_BIN does not include EdgeIQ's SQLAlchemy and Alembic dependencies: $PYTHON_BIN" >&2
  exit 1
fi

if [[ -z "$PYTHON_BIN" ]]; then
  for candidate in \
    "$APP_DIR/venv/bin/python" \
    "/Library/Frameworks/Python.framework/Versions/3.13/bin/python3" \
    "/opt/homebrew/bin/python3" \
    "/usr/local/bin/python3" \
    "/usr/bin/python3"
  do
    if python_is_ready "$candidate"; then
      PYTHON_BIN="$candidate"
      break
    fi
  done
fi

if [[ -z "$PYTHON_BIN" ]]; then
  echo "EdgeIQ could not find a Python runtime with SQLAlchemy and Alembic installed." >&2
  echo "Install the project dependencies or set PYTHON_BIN to EdgeIQ's configured Python interpreter." >&2
  exit 1
fi

echo "Using $PYTHON_BIN"
"$PYTHON_BIN" -m alembic upgrade head
exec "$PYTHON_BIN" scripts/manage_beta.py "$@"
