#!/usr/bin/env bash
set -euo pipefail

APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
ENV_FILE="$APP_DIR/.edgeiq_local_postgres.env"
COMPOSE_FILE="$APP_DIR/compose.postgres.yml"

cd "$APP_DIR"

create_credentials() {
  if [[ -e "$ENV_FILE" ]]; then
    return
  fi
  python3 - "$ENV_FILE" <<'PY'
import os
import secrets
import sys

path = sys.argv[1]
fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
with os.fdopen(fd, "w", encoding="ascii") as handle:
    handle.write(f"EDGEIQ_LOCAL_POSTGRES_PASSWORD={secrets.token_urlsafe(32)}\n")
PY
}

command="${1:-}"
case "$command" in
  start)
    create_credentials
    docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" up -d --wait db
    echo "Local PostgreSQL is ready on 127.0.0.1:${EDGEIQ_LOCAL_POSTGRES_PORT:-55432}. Desktop SQLite is unchanged."
    ;;
  schema)
    [[ -f "$ENV_FILE" ]] || { echo "Run start first." >&2; exit 1; }
    docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" --profile migration run --build --rm migrator
    ;;
  status)
    [[ -f "$ENV_FILE" ]] || { echo "Local PostgreSQL has not been started."; exit 0; }
    docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" ps db
    ;;
  preflight)
    python3 scripts/postgres_migration_preflight.py
    ;;
  stop)
    [[ -f "$ENV_FILE" ]] || exit 0
    docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" down
    echo "Local PostgreSQL stopped. Its named volume and credential are retained."
    ;;
  *)
    echo "Usage: $0 {start|schema|status|preflight|stop}" >&2
    exit 2
    ;;
esac
