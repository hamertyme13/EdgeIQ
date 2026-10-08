"""Compare two saved, same-scope briefing snapshots without provider calls."""
from __future__ import annotations

from datetime import UTC, datetime
from math import isfinite
from zoneinfo import ZoneInfo

from utils.entity_normalization import canonical_matchup_key, canonical_person_key

_GRADE_ORDER = {"PASS": 0, "MARGINAL": 1, "WATCH": 2, "STRONG": 3, "ELITE": 4}
_LANE_ORDER = {"aggressive": 0, "balanced": 1, "conservative": 2}
_LABELS = {
    "new_games": "New games", "removed_games": "Removed games",
    "new_recommendations": "New ranked props", "removed_recommendations": "No longer ranked",
    "line_changes": "Line changes", "projection_changes": "Projection changes",
    "confidence_changes": "Confidence changes", "injury_context_changes": "Injury context changes",
    "upgrades": "Upgrades", "downgrades": "Downgrades", "invalidated": "Invalidated",
}


def _number(value: object) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if isfinite(number) else None


def _game_key(game: dict) -> str:
    matchup = canonical_matchup_key(game.get("game") or game.get("matchup_label") or game.get("matchup"))
    return f"{str(game.get('sport') or '').upper()}:{matchup}" if matchup else ""


def _prop_key(prop: dict) -> str:
    player = canonical_person_key(prop.get("player"))
    stat = canonical_person_key(prop.get("stat"))
    game = canonical_matchup_key(prop.get("game"))
    game_date = str(prop.get("game_time") or "")[:10]
    if not player or not stat:
        return ""
    return "|".join((str(prop.get("sport") or "").upper(), str(prop.get("platform") or "").lower(),
                     player, stat, str(prop.get("direction") or "").lower(), game_date, game))


def _props(briefing: dict) -> dict[str, dict]:
    selected: dict[str, dict] = {}
    for prop in briefing.get("top_opportunities") or []:
        key = _prop_key(prop)
        if key and (key not in selected or (_number(prop.get("score")) or 0) > (_number(selected[key].get("score")) or 0)):
            selected[key] = prop
    return selected


def _rank(prop: dict) -> tuple[int, int, int]:
    eligibility = prop.get("recommendation_eligibility") or {}
    paid = 2 if eligibility.get("paid_ready") else 1 if eligibility.get("paper_ready") else 0
    grade = _GRADE_ORDER.get(str((prop.get("edgeiq_score") or {}).get("label") or "").upper(), -1)
    lane = _LANE_ORDER.get(str((prop.get("risk_profile") or {}).get("key") or "").lower(), -1)
    return paid, grade, lane


def compare_briefings(previous: dict | None, current: dict, *, previous_at: str = "", current_at: str = "") -> dict:
    if not isinstance(previous, dict) or not previous.get("as_of"):
        return {"available": False, "message": "No earlier briefing for this filter is saved yet.", "counts": {}, "events": []}
    try:
        earlier = datetime.fromisoformat((previous_at or str(previous["as_of"])).replace("Z", "+00:00"))
        later = datetime.fromisoformat((current_at or str(current.get("as_of") or "")).replace("Z", "+00:00"))
        earlier = earlier.replace(tzinfo=UTC) if earlier.tzinfo is None else earlier
        later = later.replace(tzinfo=UTC) if later.tzinfo is None else later
        if earlier.astimezone(ZoneInfo("America/New_York")).date() != later.astimezone(ZoneInfo("America/New_York")).date():
            return {"available": False, "message": "The previous briefing was from another day; today's changes start with the next refresh.", "counts": {}, "events": []}
    except ValueError:
        return {"available": False, "message": "The previous briefing time could not be verified.", "counts": {}, "events": []}
    before_games = {_game_key(game): game for game in previous.get("games_today") or [] if _game_key(game)}
    after_games = {_game_key(game): game for game in current.get("games_today") or [] if _game_key(game)}
    before, after = _props(previous), _props(current)
    counts = {key: 0 for key in _LABELS}
    events: list[dict] = []

    def add(kind: str, label: str, detail: str) -> None:
        counts[kind] += 1
        if len(events) < 40:
            events.append({"kind": kind, "label": label, "detail": detail})

    for key in sorted(after_games.keys() - before_games.keys()):
        add("new_games", str(after_games[key].get("matchup_label") or after_games[key].get("game") or key), "Added to displayed games")
    for key in sorted(before_games.keys() - after_games.keys()):
        add("removed_games", str(before_games[key].get("matchup_label") or before_games[key].get("game") or key), "No longer in displayed games")
    for key in sorted(before_games.keys() & after_games.keys()):
        old, new = before_games[key], after_games[key]
        old_injuries, new_injuries = str(old.get("injuries") or "").strip(), str(new.get("injuries") or "").strip()
        if old_injuries and new_injuries and old_injuries != new_injuries:
            add("injury_context_changes", str(new.get("matchup_label") or new.get("game") or key), "Recorded injury context changed; inspect the game for details")

    for key in sorted(after.keys() - before.keys()):
        prop = after[key]
        add("new_recommendations", str(prop.get("player") or "Player"), f"New ranked {prop.get('stat') or 'market'} recommendation")
    for key in sorted(before.keys() - after.keys()):
        prop = before[key]
        add("removed_recommendations", str(prop.get("player") or "Player"), f"No longer among ranked {prop.get('stat') or 'market'} recommendations")
    for key in sorted(before.keys() & after.keys()):
        old, new = before[key], after[key]
        label = f"{new.get('player') or 'Player'} · {new.get('stat') or 'Market'}"
        for field, kind, threshold in (("line", "line_changes", 0.001), ("projection", "projection_changes", 0.05), ("confidence", "confidence_changes", 0.5)):
            was, now = _number(old.get(field)), _number(new.get(field))
            if was is not None and now is not None and abs(now - was) >= threshold:
                add(kind, label, f"{field.title()}: {was:g} to {now:g}")
        if _rank(new) > _rank(old):
            add("upgrades", label, "Evidence tier, EdgeIQ grade, or risk lane improved")
        elif _rank(new) < _rank(old):
            add("downgrades", label, "Evidence tier, EdgeIQ grade, or risk lane weakened")
        old_actionable = old.get("actionable") is True or (old.get("recommendation_eligibility") or {}).get("paper_ready") is True
        new_invalid = new.get("actionable") is False or (new.get("recommendation_freshness") or {}).get("status") == "expired"
        if old_actionable and new_invalid:
            add("invalidated", label, "No longer eligible or now expired; recheck before adding")
    return {
        "available": True,
        "scope": "Displayed games and ranked props for this platform and sport; not the full provider board",
        "previous_at": previous_at or str(previous.get("as_of") or ""),
        "current_at": str(current.get("as_of") or ""),
        "counts": counts,
        "events": events,
        "event_limit": 40,
        "event_count": sum(counts.values()),
    }
