"""Preview or import exact ESPN finals for past-due NBA Points shadow rows."""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from datetime import date

from data.providers.espn import fetch_final_stats, fetch_game_times
from repository.database import SessionLocal
from repository.models.shadow_prediction_model import ShadowPredictionModel
from repository.repositories.final_stats_repository import FinalStatsRepository, _game_key
from repository.repositories.model_rehabilitation_repository import _past_game_completion_window
from scripts.audit_nba_points_shadow_pending import _eastern_day
from utils.entity_normalization import canonical_person_key


def exact_recovery_rows(pending: list[dict], finals: list[dict]) -> list[dict]:
    keys = {
        (canonical_person_key(row.get("player")), _game_key(row.get("game")), _eastern_day(row.get("game_time")))
        for row in pending
    }
    selected = []
    seen = set()
    for row in finals:
        key = (canonical_person_key(row.get("player")), _game_key(row.get("game")), str(row.get("game_date") or "")[:10])
        if (key not in keys or not all(key) or key in seen or row.get("sport") != "NBA"
                or row.get("stat") != "Points" or row.get("source") != "espn"
                or str(row.get("status") or "played").lower() not in {"played", "dnp"}):
            continue
        seen.add(key)
        selected.append(row)
    return selected


def coverage_reasons(pending: list[dict], finals: list[dict], games: list[dict]) -> dict[str, int]:
    """Explain missing finals without interpreting absence as a player outcome."""
    scheduled = {_game_key(row.get("game")) for row in games}
    points = [row for row in finals if row.get("sport") == "NBA" and row.get("stat") == "Points"]
    reasons: Counter[str] = Counter()
    for row in pending:
        player = canonical_person_key(row.get("player"))
        game = _game_key(row.get("game"))
        day = _eastern_day(row.get("game_time"))
        if not player or not game or not day:
            reason = "missing_offer_identity"
        elif game not in scheduled:
            reason = "matchup_absent_from_official_schedule"
        elif any(canonical_person_key(final.get("player")) == player
                 and _game_key(final.get("game")) == game for final in points):
            reason = "exact_box_score_match"
        elif any(canonical_person_key(final.get("player")) == player for final in points):
            reason = "player_in_different_official_game"
        else:
            reason = "player_absent_from_official_points_box_score"
        reasons[reason] += 1
    return dict(sorted(reasons.items()))


def repair(*, max_dates: int = 3, apply: bool = False) -> dict:
    with SessionLocal() as session:
        rows = (session.query(ShadowPredictionModel.player, ShadowPredictionModel.game, ShadowPredictionModel.game_time)
                .filter(ShadowPredictionModel.model_version.like("nba-points-board/%"),
                        ShadowPredictionModel.status == "shadow_pending").all())
    pending = [dict(player=row.player, game=row.game, game_time=row.game_time)
               for row in rows if _past_game_completion_window(row.game_time)]
    by_date: dict[str, list[dict]] = defaultdict(list)
    for row in pending:
        day = _eastern_day(row["game_time"])
        if day:
            by_date[day].append(row)
    chosen_dates = sorted(by_date, reverse=True)[:max(1, min(max_dates, 7))]
    selected = []
    errors = []
    coverage: Counter[str] = Counter()
    for day in chosen_dates:
        try:
            game_day = date.fromisoformat(day)
            finals = fetch_final_stats("NBA", game_day)
            games = fetch_game_times("NBA", game_day)
            selected.extend(exact_recovery_rows(by_date[day], finals))
            coverage.update(coverage_reasons(by_date[day], finals, games))
        except RuntimeError as exc:
            errors.append({"day": day, "reason": str(exc)})
    imported = FinalStatsRepository.upsert_many(selected) if apply and selected else 0
    return {
        "mode": "apply" if apply else "preview", "dates_checked": chosen_dates,
        "pending_on_dates": sum(len(by_date[day]) for day in chosen_dates),
        "exact_player_game_date_finals": len(selected), "imported": imported,
        "coverage_reasons": dict(sorted(coverage.items())),
        "errors": errors,
        "note": "No outcome is assigned here. Existing verified settlement must run after any import.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-dates", type=int, default=3)
    parser.add_argument("--apply", action="store_true", help="Import exact verified matches after preview")
    args = parser.parse_args()
    print(json.dumps(repair(max_dates=args.max_dates, apply=args.apply), indent=2))


if __name__ == "__main__":
    main()
