"""Runtime freshness status for materialized player-model inputs."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

MODEL_INPUT_MAX_AGE = timedelta(hours=12)


def model_input_status(feature_status: dict, *, now: datetime | None = None) -> dict:
    segments = max(0, int(feature_status.get("segments") or 0))
    current_segments = max(0, min(segments, int(feature_status.get("current_segments") or 0)))
    sourced_segments = max(0, min(segments, int(feature_status.get("sourced_segments") or 0)))
    coverage_known = "current_segments" in feature_status and "sourced_segments" in feature_status
    recorded = str(feature_status.get("last_materialized_at") or "").strip()
    try:
        materialized_at = datetime.fromisoformat(recorded.replace("Z", "+00:00")) if recorded else None
    except ValueError:
        materialized_at = None
    if materialized_at is not None and materialized_at.tzinfo is None:
        materialized_at = materialized_at.replace(tzinfo=UTC)
    current = now or datetime.now(UTC)
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    age = current - materialized_at if materialized_at else None
    fresh = bool(
        segments and age is not None and timedelta(0) <= age <= MODEL_INPUT_MAX_AGE
        and (not coverage_known or (current_segments == segments and sourced_segments == segments))
    )
    coverage = f"{current_segments}/{segments} caches current; {sourced_segments}/{segments} have dated source games. " if coverage_known and segments else ""
    source_date = str(feature_status.get("latest_source_game_date") or "").strip()
    return {
        "key": "features",
        "label": "Model Inputs",
        "status": "ready" if fresh else "attention",
        "value": f"{current_segments}/{segments} current" if coverage_known and segments else f"Cache current · {segments} segments" if fresh else "Refresh needed" if segments else "No features yet",
        "detail": (
            f"{coverage}Last materialized {recorded}. Latest source game {source_date or 'unknown'}. A recent cache does not prove the source stats are current."
            if materialized_at else "No player-feature refresh has been recorded."
        ),
    }
