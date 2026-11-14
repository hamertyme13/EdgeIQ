"""Preview or exclude NBA Points shadow offers confirmed Out by a dated NBA report."""

from __future__ import annotations

import argparse
import json

from data.providers.espn import fetch_final_game_outcomes
from data.providers.nba_availability import exact_out_match, fetch_report, report_day
from repository.database import SessionLocal
from repository.models.shadow_prediction_model import ShadowPredictionModel
from repository.repositories.final_stats_repository import FinalStatsRepository, _game_key
from scripts.audit_nba_points_shadow_pending import _eastern_day
from utils.time import utc_now


def confirmed_exclusion(offer: dict, report_rows: list[dict], completed_games: set[str], final: dict | None) -> dict | None:
    if _game_key(offer.get("game")) not in completed_games or final is not None:
        return None
    return exact_out_match(offer, report_rows)


def reconcile(report_url: str, *, apply: bool = False) -> dict:
    game_day = report_day(report_url)
    report_rows = fetch_report(report_url)
    if not report_rows:
        raise ValueError("The official report contained no reliably parsed player rows; nothing was changed.")
    completed_games = {_game_key(row["game"]) for row in fetch_final_game_outcomes("NBA", game_day)}
    if not completed_games:
        raise ValueError("No completed official NBA games were available for this report date.")
    checked = []
    excluded = 0
    with SessionLocal() as session:
        pending = session.query(ShadowPredictionModel).filter(
            ShadowPredictionModel.model_version.like("nba-points-board/%"),
            ShadowPredictionModel.status == "shadow_pending",
        ).all()
        for row in pending:
            if _eastern_day(row.game_time) != game_day.isoformat():
                continue
            offer = {"player": row.player, "team": row.team, "game": row.game,
                     "game_day": game_day.isoformat(), "game_time": row.game_time}
            report = exact_out_match(offer, report_rows)
            if report is None:
                continue
            final = FinalStatsRepository.find_result({
                **offer, "sport": "NBA", "stat": "Points", "platform": row.platform,
            })
            if confirmed_exclusion(offer, report_rows, completed_games, final) is None:
                continue
            checked.append({"shadow_id": row.id, "player": row.player, "game": row.game,
                            "game_day": game_day.isoformat(), "status": "Out", "source_url": report_url})
            if apply:
                row.status = "shadow_excluded"
                row.outcome_source = "nba_official_injury_report"
                row.last_attempt_at = utc_now()
                row.last_settlement_error = (
                    "Official NBA injury report listed this player Out for the exact game. "
                    f"No stat result was inferred. Source: {report_url}"
                )
                excluded += 1
        if apply and excluded:
            session.commit()
    return {
        "mode": "apply" if apply else "preview", "game_day": game_day.isoformat(),
        "report_rows": len(report_rows), "completed_games": len(completed_games),
        "confirmed_out": checked, "excluded": excluded,
        "note": "Shadow-only exclusion. Paid entries and final stats are not modified.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report_url", help="Exact dated PDF URL on ak-static.cms.nba.com")
    parser.add_argument("--apply", action="store_true", help="Exclude exact confirmed Out shadow offers")
    args = parser.parse_args()
    print(json.dumps(reconcile(args.report_url, apply=args.apply), indent=2))


if __name__ == "__main__":
    main()
