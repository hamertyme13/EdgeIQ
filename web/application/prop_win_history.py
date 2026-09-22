"""Descriptive ledger history, never an automatic forecast boost."""
from collections import defaultdict
from math import isfinite

from sqlalchemy import or_

from repository.database import SessionLocal
from repository.models.entry_prop_model import EntryPropModel
from repository.models.player_identity_model import PlayerIdentityModel
from utils.entity_normalization import canonical_matchup_key, canonical_person_key
from utils.stat_normalization import canonical_stat_label


def summarize_prop_results(rows: list[dict], stat: str, line: float | None = None) -> list[dict]:
    groups: dict[str, dict[str, int]] = defaultdict(lambda: {"wins": 0, "losses": 0, "exact_line_wins": 0, "exact_line_losses": 0})
    outcomes: dict[tuple, set[tuple[float, str]]] = defaultdict(set)
    for row in rows:
        if canonical_stat_label(row.get("stat")) != canonical_stat_label(stat):
            continue
        if (row.get("final_status") != "played" or row.get("actual") is None
                or row.get("final_result") not in {"Win", "Loss"}
                or not row.get("final_source")
                or row["final_source"] in {"projection_estimate", "integrity_quarantine", "manual", "unknown", "unmatched"}):
            continue
        direction = str(row.get("direction") or "").title()
        if direction not in {"Over", "Under"}:
            continue
        try:
            actual, recorded_line = float(row["actual"]), float(row["line"])
        except (TypeError, ValueError, KeyError):
            continue
        if not isfinite(actual) or not isfinite(recorded_line):
            continue
        event = ((canonical_matchup_key(row["game"]), str(row["game_time"])[:10])
                 if row.get("game") and row.get("game_time") else row.get("provider_event_id"))
        if not event:
            continue
        key = (event, recorded_line, direction)
        outcomes[key].add((actual, row["final_result"]))
    for (_, recorded_line, direction), results in outcomes.items():
        # Conflicting duplicate evidence is withheld, not resolved by row order.
        if len(results) != 1:
            continue
        actual, result = next(iter(results))
        if actual == recorded_line:
            continue
        expected = "Win" if ((actual > recorded_line) == (direction == "Over")) else "Loss"
        if result != expected:
            continue
        category = "wins" if result == "Win" else "losses"
        groups[direction][category] += 1
        if line is not None and recorded_line == line:
            groups[direction][f"exact_line_{category}"] += 1
    return [{"direction": direction, **counts,
             "label": ("Won before: " if counts["wins"] else "No recorded wins: ")
             + f"{counts['wins']} wins / {counts['wins'] + counts['losses']} settled lines"}
            for direction, counts in sorted(groups.items())]


def player_prop_win_history(player: str, sport: str, stat: str, line: float | None = None) -> list[dict]:
    if not sport or sport == "All Sports":
        return []
    with SessionLocal() as session:
        identities = session.query(PlayerIdentityModel.id).filter(
            PlayerIdentityModel.canonical_key == canonical_person_key(player),
            PlayerIdentityModel.sport == sport.upper(),
        )
        rows = session.query(EntryPropModel).filter(
            EntryPropModel.sport == sport.upper(),
            or_(EntryPropModel.player_name == player, EntryPropModel.player_identity_id.in_(identities)),
            EntryPropModel.final_result.in_(["Win", "Loss"]),
        ).order_by(EntryPropModel.id.desc()).limit(500).all()
        fields = ("stat", "direction", "line", "game", "game_time", "provider_event_id",
                  "actual", "final_status", "final_source", "final_result")
        return summarize_prop_results([{field: getattr(row, field) for field in fields} for row in rows], stat, line)
