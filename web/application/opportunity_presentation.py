from __future__ import annotations

from analytics.opportunity_score import opportunity_score, score_input_digest, score_source_freshness
from utils.entity_normalization import canonical_person_key
from utils.stat_normalization import canonical_stat_label


def best_offer_per_market(rows: list[dict]) -> list[dict]:
    """Keep the strongest offered line per player/stat/game/provider."""
    winners: dict[tuple, dict] = {}
    for row in rows:
        key = (
            str(row.get("sport") or row.get("league") or "").upper(),
            canonical_person_key(row.get("player")),
            canonical_stat_label(row.get("stat")),
            str(row.get("game") or row.get("game_time") or "").casefold(),
            str(row.get("platform") or "").casefold(),
        )
        current = winners.get(key)
        if current is None or _offer_rank(row) > _offer_rank(current):
            winners[key] = row
    return sorted(winners.values(), key=_offer_rank, reverse=True)


def best_offer_per_player(rows: list[dict]) -> list[dict]:
    """Keep the strongest scored opportunity for each player on a daily board."""
    winners: dict[tuple[str, str], dict] = {}
    for row in rows:
        key = (
            str(row.get("sport") or row.get("league") or "").upper(),
            canonical_person_key(row.get("player")),
        )
        if not key[1]:
            continue
        current = winners.get(key)
        if current is None or _offer_rank(row) > _offer_rank(current):
            winners[key] = row
    return sorted(winners.values(), key=_offer_rank, reverse=True)


def _offer_rank(row: dict) -> tuple[int, float, int, float]:
    return (
        int(bool(row.get("market_supported"))),
        float(row.get("score") or row.get("grade_score") or 0.0),
        int(not row.get("adjusted_line")),
        float(row.get("confidence") or 0.0),
    )


def presented_score(prop: dict) -> dict:
    stored = prop.get("edgeiq_score") or {}
    if (stored.get("snapshot_id")
            and stored.get("snapshot_id") == prop.get("recommendation_snapshot_id")
            and stored.get("input_digest") == score_input_digest(prop)):
        return stored
    return opportunity_score(prop)


def scored_opportunities(payload: dict, field: str) -> dict:
    """Reuse locked scores; legacy rows remain explicitly response-time scores."""
    if field not in payload:
        return payload
    return {**payload, field: [
        {**prop, "edgeiq_score": presented_score(prop),
         "edgeiq_score_freshness": score_source_freshness(prop)} for prop in payload.get(field) or []
    ]}
