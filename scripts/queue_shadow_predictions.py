from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from analytics.edgeiq_model import MODEL_VERSION
from analytics.prediction_evidence import independent_market_key
from repository.repositories.model_rehabilitation_repository import ModelRehabilitationRepository
from web.app import _analyzed_feed_prop, _end_to_end_prop_eligibility, _fetch_props, _is_prop_on_entry_day


def main() -> int:
    current = ModelRehabilitationRepository.shadow_status()["queued"]
    needed = max(0, 227 - current)
    raw = sorted(
        _fetch_props("Both", None),
        key=lambda row: int(row.get("trending_count") or 0),
        reverse=True,
    )
    rows = []
    seen = set()
    for prop in raw:
        if not _is_prop_on_entry_day(prop) or not _end_to_end_prop_eligibility(prop)["eligible"]:
            continue
        key = independent_market_key(prop)
        if key in seen:
            continue
        seen.add(key)
        rows.append(_analyzed_feed_prop(prop))
        if len(rows) >= needed:
            break
    ModelRehabilitationRepository.save_feed({
        "feed": {
            "id": "edgeiq-recommendation-snapshot-v2.2",
            "canonical": True,
            "platform": "Both",
            "sport": "All Sports",
        },
        "analyzed_props": rows,
    })
    result = ModelRehabilitationRepository.queue_shadow(
        rows,
        model_version=f"{MODEL_VERSION}-shadow-v2.2",
        target=227,
    )
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
