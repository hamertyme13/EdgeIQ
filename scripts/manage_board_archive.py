"""Preview or run a reversible, backup-gated raw-offer archive batch."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.board_payload_archive import archive_board_payload_batch, restore_board_payload_batch


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", help="Override the database; defaults to EdgeIQ's configured SQLite file.")
    parser.add_argument("--archive-dir", default=".edgeiq_archives")
    parser.add_argument("--backup-path", help="Required for --execute; must be a separate completed SQLite backup.")
    parser.add_argument("--retention-days", type=int, default=21)
    parser.add_argument("--limit", type=int, default=1000)
    parser.add_argument("--execute", action="store_true", help="Archive one capped batch; default is read-only preview.")
    parser.add_argument("--restore", help="Restore raw payloads from a prior archive file.")
    args = parser.parse_args()
    if args.restore:
        result = {"restored_payloads": restore_board_payload_batch(args.restore, database_url=args.database_url)}
    else:
        result = archive_board_payload_batch(
            database_url=args.database_url, archive_dir=args.archive_dir,
            backup_path=args.backup_path, retention_days=args.retention_days,
            limit=args.limit, execute=args.execute,
        )
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
