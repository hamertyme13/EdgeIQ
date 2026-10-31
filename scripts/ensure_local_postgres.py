"""Start the opt-in local PostgreSQL cluster before desktop or scheduler work."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parents[1]
POSTGRES_BIN = Path("/opt/homebrew/opt/postgresql@17/bin")
POSTGRES_DATA = Path("/opt/homebrew/var/postgresql@17")
POSTGRES_LOG = Path("/private/tmp/edgeiq-postgres.log")


def ensure_local_postgres() -> None:
    load_dotenv(ROOT / ".env")
    if ((ROOT / ".edgeiq_postgres_cutover").exists()
            and os.getenv("EDGEIQ_LOCAL_POSTGRES") not in {"0", "1"}):
        raise RuntimeError("EdgeIQ was migrated to PostgreSQL. Restore its local DATABASE_URL and enable the local server.")
    if os.getenv("EDGEIQ_LOCAL_POSTGRES") != "1":
        return
    url = make_url(os.getenv("DATABASE_URL", ""))
    if (url.get_backend_name() != "postgresql" or url.host not in {"127.0.0.1", "localhost"}
            or url.port != 55432 or url.database != "edgeiq_staging"):
        raise RuntimeError("Local PostgreSQL is enabled, but DATABASE_URL does not point to the EdgeIQ local database.")
    ready = [str(POSTGRES_BIN / "pg_isready"), "-h", "127.0.0.1", "-p", "55432"]
    if subprocess.run(ready, capture_output=True, check=False, timeout=5).returncode != 0:
        if not POSTGRES_DATA.is_dir():
            raise RuntimeError("EdgeIQ's local PostgreSQL data directory is missing.")
        subprocess.run(
            [str(POSTGRES_BIN / "pg_ctl"), "-D", str(POSTGRES_DATA),
             "-o", "-h 127.0.0.1 -p 55432", "-l", str(POSTGRES_LOG), "start"],
            check=True, capture_output=True, timeout=30,
        )
    if subprocess.run(ready, capture_output=True, check=False, timeout=5).returncode != 0:
        raise RuntimeError("EdgeIQ's local PostgreSQL server did not become ready.")


if __name__ == "__main__":
    ensure_local_postgres()
