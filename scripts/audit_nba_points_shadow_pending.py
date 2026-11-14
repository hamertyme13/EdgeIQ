"""Read-only coverage audit for past-due NBA Points shadow forecasts."""

from __future__ import annotations

import json
from collections import Counter
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from repository.database import SessionLocal
from repository.models.final_player_stat_model import FinalPlayerStatModel
from repository.models.shadow_prediction_model import ShadowPredictionModel
from repository.repositories.final_stats_repository import _game_key
from repository.repositories.model_rehabilitation_repository import _past_game_completion_window
from utils.entity_normalization import canonical_person_key

EASTERN = ZoneInfo("America/New_York")


def _eastern_day(value: str) -> str | None:
    try:
        stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    stamp = stamp.replace(tzinfo=UTC) if stamp.tzinfo is None else stamp.astimezone(UTC)
    return stamp.astimezone(EASTERN).date().isoformat()


def classify_pending(pending: list[dict], finals: list[dict]) -> dict:
    """Classify coverage, not outcomes; no unmatched row is graded by this audit."""
    exact = {(canonical_person_key(row.get("player")), str(row.get("game_date") or "")[:10])
             for row in finals if row.get("player") and row.get("game_date")}
    nearby_games = {
        (canonical_person_key(row.get("player")), str(row.get("game_date") or "")[:10], _game_key(row.get("game")))
        for row in finals if row.get("player") and row.get("game_date") and row.get("game")
    }
    dates = {str(row.get("game_date") or "")[:10] for row in finals}
    by_reason: Counter[str] = Counter()
    by_day: dict[str, Counter[str]] = {}
    for row in pending:
        day = _eastern_day(str(row.get("game_time") or ""))
        player_key = canonical_person_key(row.get("player"))
        if not day or not player_key:
            reason = "missing_pregame_identity_or_time"
        elif (player_key, day) in exact:
            reason = "player_day_final_exists_match_needs_review"
        elif _game_key(row.get("game")) and any(
            (player_key, (date.fromisoformat(day) + timedelta(days=offset)).isoformat(), _game_key(row.get("game")))
            in nearby_games for offset in (-1, 1)
        ):
            reason = "same_matchup_nearby_day_requires_review"
        elif day in dates:
            reason = "player_day_points_final_absent"
        else:
            reason = "nba_points_feed_absent_for_day"
        by_reason[reason] += 1
        by_day.setdefault(day or "unknown", Counter())[reason] += 1
    return {
        "pending": len(pending), "by_reason": dict(sorted(by_reason.items())),
        "by_game_day": {day: dict(sorted(counts.items())) for day, counts in sorted(by_day.items())},
        "note": "Coverage diagnostics only. Absence is not a loss or DNP; exact-game and source verification remain required.",
    }


def audit_pending() -> dict:
    with SessionLocal() as session:
        pending_rows = (session.query(ShadowPredictionModel.player, ShadowPredictionModel.game, ShadowPredictionModel.game_time)
                        .filter(ShadowPredictionModel.model_version.like("nba-points-board/%"),
                                ShadowPredictionModel.status == "shadow_pending")
                        .all())
        due = [row for row in pending_rows if _past_game_completion_window(row.game_time)]
        pending = [{"player": row.player, "game": row.game, "game_time": row.game_time} for row in due]
        days = {_eastern_day(row["game_time"]) for row in pending}
        days.discard(None)
        query_days = {
            (date.fromisoformat(day) + timedelta(days=offset)).isoformat()
            for day in days for offset in (-1, 0, 1)
        }
        finals_rows = (session.query(FinalPlayerStatModel.player, FinalPlayerStatModel.game, FinalPlayerStatModel.game_date)
                       .filter(FinalPlayerStatModel.sport == "NBA",
                               FinalPlayerStatModel.stat == "Points",
                               FinalPlayerStatModel.game_date.in_(query_days)).all()) if days else []
        finals = [{"player": row.player, "game": row.game, "game_date": row.game_date} for row in finals_rows]
    return {**classify_pending(pending, finals), "deferred_future": len(pending_rows) - len(due)}


if __name__ == "__main__":
    print(json.dumps(audit_pending(), indent=2))
