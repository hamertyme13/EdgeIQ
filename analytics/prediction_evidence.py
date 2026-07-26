from __future__ import annotations

import hashlib

from utils.entity_normalization import canonical_matchup_key, canonical_person_key
from utils.stat_normalization import canonical_stat_label


def independent_market_key(prop: dict) -> str:
    parts = (
        canonical_person_key(prop.get("player") or prop.get("player_name")),
        str(prop.get("sport") or "").strip().upper(),
        canonical_stat_label(prop.get("stat") or ""),
        _number(prop.get("line")),
        str(prop.get("direction") or "Over").strip().lower(),
        canonical_matchup_key(prop.get("game") or ""),
        str(prop.get("game_time") or "")[:10],
    )
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def offer_key(prop: dict) -> str:
    parts = (
        independent_market_key(prop),
        str(prop.get("platform") or "").strip().lower(),
        str(prop.get("line_offer_type") or "standard").strip().lower(),
    )
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def deduplicate_outcomes(rows: list[dict]) -> list[dict]:
    selected: dict[str, dict] = {}
    for row in rows:
        key = row.get("independent_market_key") or independent_market_key(row)
        existing = selected.get(key)
        if existing is None or _quality(row) > _quality(existing):
            selected[key] = {**row, "independent_market_key": key}
    return list(selected.values())


def _quality(row: dict) -> tuple[int, int, str]:
    verified = str(row.get("final_source") or row.get("outcome_source") or "").lower() not in {
        "", "unknown", "unmatched", "projection_estimate"
    }
    has_identity = bool(row.get("player_identity_id"))
    return int(verified), int(has_identity), str(row.get("predicted_at") or row.get("placed_at") or "")


def _number(value: object) -> str:
    try:
        return f"{float(str(value)):.4f}"
    except (TypeError, ValueError):
        return "0.0000"
