"""Runtime freshness status for materialized player-model inputs."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

MODEL_INPUT_MAX_AGE = timedelta(hours=12)


def model_input_status(
    feature_status: dict, *, source_checks: dict[str, bool] | None = None, now: datetime | None = None,
) -> dict:
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
    cache_fresh = bool(
        segments and age is not None and timedelta(0) <= age <= MODEL_INPUT_MAX_AGE
        and (not coverage_known or (current_segments == segments and sourced_segments == segments))
    )
    sports = {str(sport).upper() for sport in feature_status.get("sports") or [] if sport}
    missing_checks = sorted(sport for sport in sports if source_checks is not None and not source_checks.get(sport))
    source_check_known = source_checks is not None and bool(sports)
    fresh = cache_fresh and (not source_check_known or not missing_checks)
    coverage = f"{current_segments}/{segments} caches current; {sourced_segments}/{segments} have dated source games. " if coverage_known and segments else ""
    source_date = str(feature_status.get("latest_source_game_date") or "").strip()
    source_detail = (
        f" Daily source checks still needed for {', '.join(missing_checks)}."
        if missing_checks else " Daily source checks recorded for cached sports; this does not prove every final stat is complete."
        if source_check_known else " Daily source-check coverage is unavailable."
    )
    return {
        "key": "features",
        "label": "Model Inputs",
        "status": "ready" if fresh else "attention",
        "value": f"{current_segments}/{segments} current" if coverage_known and segments else f"Cache current · {segments} segments" if fresh else "Refresh needed" if segments else "No features yet",
        "source_checks": "needed" if missing_checks else "checked" if source_check_known else "unknown",
        "unchecked_sports": missing_checks,
        "detail": (
            f"{coverage}Last materialized {recorded}. Latest source game {source_date or 'unknown'}. A recent cache does not prove the source stats are current.{source_detail}"
            if materialized_at else "No player-feature refresh has been recorded."
        ),
    }
