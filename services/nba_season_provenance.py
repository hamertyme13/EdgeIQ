"""Backfill NBA final-stat season labels from exact cached ESPN events."""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, date, datetime

from sqlalchemy.orm import Session

from data.providers.cache import _cache_path, _read_cache
from data.providers.espn import _BASE, _event_matchup, _event_season_type
from repository.models.final_player_stat_model import FinalPlayerStatModel
from utils.entity_normalization import canonical_matchup_key


def _cached_scoreboard(game_date: str) -> dict | None:
    url = f"{_BASE}/basketball/nba/scoreboard?dates={game_date.replace('-', '')}"
    cached = _read_cache(_cache_path(url))
    return cached.data if cached and isinstance(cached.data, dict) else None


def _season_start(today: date) -> str:
    year = today.year if today.month >= 9 else today.year - 1
    return f"{year}-09-15"


def backfill_nba_season_type(
    session: Session,
    *,
    limit_dates: int = 30,
    apply: bool = False,
    today: date | None = None,
    scoreboard_loader=_cached_scoreboard,
) -> dict:
    """Match exact completed games; leave ambiguous and uncached rows untouched."""
    if not 1 <= limit_dates <= 366:
        raise ValueError("limit_dates must be between 1 and 366")
    cutoff = today or datetime.now(UTC).date()
    dates = [
        row[0] for row in (
            session.query(FinalPlayerStatModel.game_date)
            .filter(
                FinalPlayerStatModel.sport == "NBA",
                FinalPlayerStatModel.stat == "Points",
                FinalPlayerStatModel.season_type.is_(None),
                FinalPlayerStatModel.game_date >= _season_start(cutoff),
                FinalPlayerStatModel.game_date <= cutoff.isoformat(),
            )
            .distinct()
            .order_by(FinalPlayerStatModel.game_date.desc())
            .limit(limit_dates)
        )
    ]
    report = {
        "mode": "apply" if apply else "preview",
        "dates_checked": len(dates),
        "cache_misses": 0,
        "unlabeled_events": 0,
        "ambiguous_games": 0,
        "matched_games": 0,
        "rows": 0,
    }
    for day in dates:
        scoreboard = scoreboard_loader(day)
        if not scoreboard:
            report["cache_misses"] += 1
            continue
        events: dict[str, list[str | None]] = defaultdict(list)
        for event in scoreboard.get("events") or []:
            competitions = event.get("competitions") or []
            competition = competitions[0] if competitions else {}
            if not ((competition.get("status") or {}).get("type") or {}).get("completed"):
                continue
            key = canonical_matchup_key(_event_matchup(event))
            if not key or "@" not in key:
                continue
            season_type = _event_season_type(event)
            if not season_type:
                report["unlabeled_events"] += 1
            events[key].append(season_type)
        games = (
            session.query(FinalPlayerStatModel.game)
            .filter(
                FinalPlayerStatModel.sport == "NBA",
                FinalPlayerStatModel.game_date == day,
                FinalPlayerStatModel.season_type.is_(None),
            )
            .distinct()
            .all()
        )
        for (game,) in games:
            labels = events.get(canonical_matchup_key(game), [])
            if len(labels) != 1 or labels[0] is None:
                if len(labels) > 1:
                    report["ambiguous_games"] += 1
                continue
            query = session.query(FinalPlayerStatModel).filter(
                FinalPlayerStatModel.sport == "NBA",
                FinalPlayerStatModel.game_date == day,
                FinalPlayerStatModel.game == game,
                FinalPlayerStatModel.season_type.is_(None),
            )
            count = query.count()
            if not count:
                continue
            report["matched_games"] += 1
            report["rows"] += count
            if apply:
                query.update({FinalPlayerStatModel.season_type: labels[0]}, synchronize_session=False)
    if apply:
        session.commit()
    return report
