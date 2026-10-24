"""Preview or apply exact NBA season provenance from locally cached ESPN finals."""

from __future__ import annotations

import argparse
import json

from repository.database import SessionLocal
from services.nba_season_provenance import backfill_nba_season_type


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit-dates", type=int, default=30)
    parser.add_argument("--apply", action="store_true", help="Persist labels after exact event matching")
    args = parser.parse_args()
    with SessionLocal() as session:
        report = backfill_nba_season_type(session, limit_dates=args.limit_dates, apply=args.apply)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
