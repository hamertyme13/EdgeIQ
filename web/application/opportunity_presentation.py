from __future__ import annotations

from analytics.opportunity_score import opportunity_score, score_input_digest, score_source_freshness


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
