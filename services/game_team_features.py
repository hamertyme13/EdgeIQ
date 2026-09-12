from __future__ import annotations

from datetime import UTC, datetime
from statistics import mean

from utils.entity_normalization import canonical_person_key


def team_history_features(
    sport: str,
    home_team: str,
    away_team: str,
    game_start: str,
    settled_games: list[dict],
    injuries: list[dict] | None = None,
) -> dict:
    """Build pre-game, outcome-only team evidence for the shadow game challenger."""
    valid_games = _prior_games(settled_games, game_start)
    home_rows = _team_rows(home_team, valid_games)
    away_rows = _team_rows(away_team, valid_games)
    home = _summary(sport, home_team, home_rows, game_start)
    away = _summary(sport, away_team, away_rows, game_start)
    sample_size = min(home["sample_size"], away["sample_size"])
    historical_home_probability = _historical_probability(home, away, sample_size)
    margin_residual = _margin_residual(home, away, sample_size)
    return {
        "historical_home_probability": historical_home_probability,
        "historical_sample_size": sample_size,
        "historical_game_ids": sorted({str(row.get("game_id") or "") for row in home_rows + away_rows}),
        "historical_sources": sorted({str(row.get("source") or "") for row in home_rows + away_rows if row.get("source")}),
        "historical_as_of": game_start,
        "historical_margin_residual": margin_residual,
        "historical_expected_home_points": _expected_points(home, away),
        "historical_expected_away_points": _expected_points(away, home),
        "team_features": {
            "home": home,
            "away": away,
            "sport_specific": str(sport or "").upper() in {"NBA", "WNBA"},
            "injuries": _injury_context(home_team, away_team, injuries or [], game_start),
        },
    }


def _team_rows(team: str, rows: list[dict]) -> list[dict]:
    target = _team_key(team)
    matched = []
    for row in rows:
        if target and (_matches_side(row, team, "home") or _matches_side(row, team, "away")):
            matched.append(row)
    return sorted(matched, key=lambda row: str(row.get("game_start") or ""), reverse=True)


def _summary(sport: str, team: str, rows: list[dict], game_start: str) -> dict:
    recent = rows[:10]
    home_rows = [row for row in rows if _matches_side(row, team, "home")]
    away_rows = [row for row in rows if _matches_side(row, team, "away")]
    wins = [_won(row, team) for row in recent]
    points_for = [_points_for(row, team) for row in recent]
    points_against = [_points_against(row, team) for row in recent]
    return {
        "team": team,
        "sample_size": len(rows),
        "recent_sample_size": len(recent),
        "recent_win_rate": _average(wins),
        "scoring_differential": _difference(points_for, points_against),
        "offensive_performance": _average(points_for),
        "defensive_performance": _average(points_against),
        "estimated_pace": _average([float(row["pace"]) for row in recent if row.get("pace") is not None]),
        "pace_source": "box_score_possessions" if any(row.get("pace") is not None for row in recent) else "unavailable",
        "home_win_rate": _average([_won(row, team) for row in home_rows]),
        "away_win_rate": _average([_won(row, team) for row in away_rows]),
        "rest_days": _rest_days(game_start, rows),
    }


def _historical_probability(home: dict, away: dict, sample_size: int) -> float:
    if sample_size <= 0:
        return 0.5
    home_strength = float(home["recent_win_rate"] if home["recent_win_rate"] is not None else 0.5)
    away_strength = float(away["recent_win_rate"] if away["recent_win_rate"] is not None else 0.5)
    home_split = float(home["home_win_rate"] if home["home_win_rate"] is not None else home_strength)
    away_split = float(away["away_win_rate"] if away["away_win_rate"] is not None else away_strength)
    probability = (home_strength + (1.0 - away_strength) + home_split + (1.0 - away_split)) / 4.0
    probability = (probability * sample_size + 5.0) / (sample_size + 10.0)
    return round(max(0.05, min(0.95, probability)), 4)


def _margin_residual(home: dict, away: dict, sample_size: int) -> float:
    if sample_size <= 0:
        return 0.0
    home_diff = float(home["scoring_differential"] or 0.0)
    away_diff = float(away["scoring_differential"] or 0.0)
    return round(max(-12.0, min(12.0, (home_diff - away_diff) * 0.25)), 3)


def _injury_context(home_team: str, away_team: str, injuries: list[dict], game_start: str) -> dict:
    rows = [
        row for row in injuries
        if row.get("verified") is True and row.get("source") and row.get("captured_at")
        and _injury_is_current(row, game_start)
        and ({_team_key(str(row.get("team") or "")), _team_key(str(row.get("team_name") or ""))}
             & {_team_key(home_team), _team_key(away_team)})
    ]
    return {
        "verified": bool(rows),
        "source": "espn_injury_feed" if rows else "unavailable",
        "reported_count": len(rows),
        "reports": [
            {"player": str(row.get("player") or ""), "team": str(row.get("team") or row.get("team_name") or ""), "status": str(row.get("status") or ""), "captured_at": row["captured_at"]}
            for row in rows[:12]
        ],
    }


def _injury_is_current(row: dict, game_start: str) -> bool:
    try:
        captured = datetime.fromisoformat(str(row["captured_at"]).replace("Z", "+00:00"))
        target = datetime.fromisoformat(game_start.replace("Z", "+00:00"))
        captured = captured.replace(tzinfo=UTC) if captured.tzinfo is None else captured.astimezone(UTC)
        target = target.replace(tzinfo=UTC) if target.tzinfo is None else target.astimezone(UTC)
        now = datetime.now(UTC)
        return captured <= target and 0 <= (now - captured).total_seconds() <= 3600
    except (ValueError, TypeError, KeyError):
        return False


def _won(row: dict, team: str) -> float:
    is_home = _matches_side(row, team, "home")
    home_win = float(row.get("actual_home_win") or 0.0)
    return home_win if is_home else 1.0 - home_win


def _points_for(row: dict, team: str) -> float:
    return float(row.get("actual_home_points") or 0.0) if _matches_side(row, team, "home") else float(row.get("actual_away_points") or 0.0)


def _points_against(row: dict, team: str) -> float:
    return float(row.get("actual_away_points") or 0.0) if _matches_side(row, team, "home") else float(row.get("actual_home_points") or 0.0)


def _matches_side(row: dict, team: str, side: str) -> bool:
    aliases = [row.get(f"{side}_team"), *(row.get(f"{side}_aliases") or [])]
    return bool(_team_key(team)) and _team_key(team) in {_team_key(str(value)) for value in aliases if value}


def _expected_points(team: dict, opponent: dict) -> float | None:
    offense = team.get("offensive_performance")
    defense = opponent.get("defensive_performance")
    return (float(offense) + float(defense)) / 2 if offense is not None and defense is not None else None


def _prior_games(rows: list[dict], game_start: str) -> list[dict]:
    try:
        target = datetime.fromisoformat(game_start.replace("Z", "+00:00"))
        target = target.replace(tzinfo=UTC) if target.tzinfo is None else target.astimezone(UTC)
    except ValueError:
        return []
    games: dict[str, dict] = {}
    for row in rows:
        try:
            started = datetime.fromisoformat(str(row.get("game_start") or "").replace("Z", "+00:00"))
            started = started.replace(tzinfo=UTC) if started.tzinfo is None else started.astimezone(UTC)
        except ValueError:
            continue
        if started >= target or row.get("actual_home_win") not in (0.0, 1.0):
            continue
        if row.get("actual_home_points") is None or row.get("actual_away_points") is None:
            continue
        games.setdefault(str(row.get("game_id") or started.isoformat()), row)
    return list(games.values())


def _rest_days(game_start: str, rows: list[dict]) -> int | None:
    if not game_start or not rows:
        return None
    try:
        target = datetime.fromisoformat(game_start.replace("Z", "+00:00"))
        latest = datetime.fromisoformat(str(rows[0].get("game_start") or "").replace("Z", "+00:00"))
    except ValueError:
        return None
    return max(0, (target.date() - latest.date()).days)


def _average(values: list[float]) -> float | None:
    return round(mean(values), 4) if values else None


def _difference(left: list[float], right: list[float]) -> float | None:
    return round((_average(left) or 0.0) - (_average(right) or 0.0), 3) if left else None


def _team_key(team: str) -> str:
    return canonical_person_key(team)
