from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from repository.database import initialize_database
from web.app import _run_due_daily_operations


def main() -> int:
    initialize_database()
    print(json.dumps(_run_due_daily_operations(), default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
