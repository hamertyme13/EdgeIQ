from __future__ import annotations

from sqlalchemy import func

from utils.stat_normalization import canonical_stat_label

ROLE_STATS = {
    "Minutes", "Field Goals Attempted", "Free Throws Attempted", "3-Pointers Attempted",
    "Passing Attempts", "Pass Attempts", "Rush Attempts", "Carries", "Targets",
    "Snaps", "Routes", "Route Participation", "At Bats", "Plate Appearances",
    "Batters Faced", "Pitches", "Innings Pitched", "Shots on Goal", "Time on Ice", "Shifts",
    "Kicking Field Goals Attempted", "Extra Points Attempted",
}


def attach_opportunity_context(session, history: list[dict], identity: dict | None, player: str, sport: str | None, team: str = "") -> None:
    """Attach role-volume evidence without making the final-stat repository own forecasting features."""
    if not history:
        return
    from repository.models.final_player_stat_model import FinalPlayerStatModel
    from utils.entity_normalization import canonical_person_key

    query = session.query(FinalPlayerStatModel).filter(FinalPlayerStatModel.stat.in_(ROLE_STATS))
    if identity:
        query = query.filter(FinalPlayerStatModel.player_identity_id == identity["id"])
    else:
        player_key = canonical_person_key(player)
        matching_ids = [
            row.id for row in session.query(FinalPlayerStatModel.id).filter(
                func.lower(FinalPlayerStatModel.player) == str(player).strip().lower()
            ).all()
        ]
        if not matching_ids:
            matching_ids = [
                row.id for row in session.query(FinalPlayerStatModel.id, FinalPlayerStatModel.player).all()
                if canonical_person_key(row.player) == player_key
            ]
        query = query.filter(FinalPlayerStatModel.id.in_(matching_ids))
    if sport:
        query = query.filter(FinalPlayerStatModel.sport == sport.upper())
    game_dates = {
        str(row.get("game_date") or "").strip()
        for row in history
        if str(row.get("game_date") or "").strip()
    }
    if game_dates:
        query = query.filter(FinalPlayerStatModel.game_date.in_(game_dates))

    context: dict[tuple[str, str], dict[str, float]] = {}
    context_limit = max(100, min(2000, len(history) * len(ROLE_STATS)))
    for row in query.limit(context_limit).all():
        context.setdefault((str(row.game_date or ""), _game_key(row.game)), {})[row.stat] = float(row.actual)
    for row in history:
        values = context.get((str(row.get("game_date") or ""), _game_key(row.get("game"))), {})
        if "Minutes" in values:
            row["minutes"] = values["Minutes"]
        opportunities = role_opportunities(str(row.get("sport") or sport or ""), str(row.get("stat") or ""), values)
        if opportunities is not None:
            row["opportunities"] = opportunities


def role_opportunities(sport: str, stat: str, values: dict[str, float]) -> float | None:
    sport_key = sport.upper()
    stat_key = canonical_stat_label(stat).lower()
    if sport_key in {"WNBA", "NBA"}:
        scoring_attempts = sum(
            values.get(label, 0.0)
            for label in ("Field Goals Attempted", "Free Throws Attempted")
        )
        if any(token in stat_key for token in ("point", "three", "field goal", "free throw")):
            return scoring_attempts or values.get("Field Goals Attempted")
        return values.get("Minutes")
    if sport_key == "NFL":
        if "pass" in stat_key or "completion" in stat_key or "interception" in stat_key:
            return values.get("Passing Attempts", values.get("Pass Attempts"))
        if "rush" in stat_key or "carr" in stat_key:
            return values.get("Rush Attempts", values.get("Carries"))
        if "rec" in stat_key or "target" in stat_key:
            return values.get("Targets", values.get("Routes"))
        if "field goal" in stat_key:
            return values.get("Kicking Field Goals Attempted", values.get("Field Goals Attempted"))
        if "extra point" in stat_key:
            return values.get("Extra Points Attempted")
        return values.get("Snaps")
    if sport_key == "MLB":
        if any(token in stat_key for token in ("strikeout", "pitch", "earned run", "walks allowed")):
            return values.get("Batters Faced", values.get("Pitches", values.get("Innings Pitched")))
        return values.get("Plate Appearances", values.get("At Bats"))
    if sport_key == "NHL":
        return values.get("Time on Ice", values.get("Shifts", values.get("Shots on Goal")))
    return None


def _game_key(value: object) -> str:
    return str(value or "").upper().replace(" ", "")
