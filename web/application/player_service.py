from __future__ import annotations

from collections.abc import Callable

from analytics.hit_rate import estimate_hit_rate
from repository.repositories.line_history_repository import LineHistoryRepository
from repository.repositories.player_identity_repository import PlayerIdentityRepository
from utils.entity_normalization import canonical_person_key


class PlayerLookupError(ValueError):
    pass


def player_detail_payload(
    player_name: str,
    platform: str,
    sport: str,
    *,
    fetch_props: Callable[[str, str | None], list[dict]],
    build_detail: Callable[[str, list[dict]], dict],
) -> dict:
    sport_filter = None if sport == "All Sports" else sport.upper()
    player_key = canonical_person_key(player_name)
    props = [
        prop
        for prop in fetch_props(platform, sport_filter)
        if canonical_person_key(prop.get("player")) == player_key
    ]
    if not props:
        raise PlayerLookupError(f"No active props found for {player_name}.")
    props.sort(key=lambda prop: prop.get("trending_count", 0), reverse=True)
    return build_detail(player_name, props)


def player_identity_payload(player_name: str, sport: str, team: str) -> dict:
    identity = PlayerIdentityRepository.resolve(player_name, sport, team, create=False)
    if identity is None:
        raise PlayerLookupError("No saved player identity matches that name and sport yet.")
    return {**identity, "aliases": PlayerIdentityRepository.aliases(identity["id"])}


def player_line_movement_payload(
    player_name: str,
    stat: str,
    platform: str,
    *,
    active_line: Callable[[str, str, str], float | None],
    build_movement: Callable[..., dict],
) -> dict:
    history = LineHistoryRepository.get_history(player_name, stat, platform)
    current = active_line(player_name, stat, platform)
    return build_movement(player_name, stat, platform, history, current_line=current)


def player_hit_rate_payload(
    player_name: str,
    stat: str,
    line: float,
    projection: float | None,
    trending_count: int,
    sport: str | None,
) -> dict:
    summary = estimate_hit_rate(player_name, stat, line, projection, trending_count, sport)
    return {
        "player": summary.player,
        "stat": summary.stat,
        "line": summary.line,
        "projection": summary.projection,
        "edge": summary.edge,
        "estimated_hit_rate": summary.estimated_hit_rate,
        "last_5": summary.last_5,
        "last_10": summary.last_10,
        "season": summary.season,
        "source": summary.source,
        "sample_size": summary.sample_size,
        "note": summary.note,
    }
