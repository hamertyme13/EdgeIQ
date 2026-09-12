from __future__ import annotations

from collections.abc import Callable

from repository.repositories.entry_repository import EntryRepository
from utils.entity_normalization import canonical_matchup_key, canonical_person_key


def game_group_key(sport: str, game: str) -> str:
    """Group provider matchup labels without crossing league-specific aliases."""
    aliases = dict(EntryRepository.TEAM_ALIASES)
    if sport.upper() == "NFL":
        aliases["LA"] = "LAR"
    return canonical_matchup_key(game, aliases)


def trending_games_payload(
    props: list[dict],
    ranked_props: list[dict],
    limit: int,
    *,
    group_key: Callable[[str, str], str] = game_group_key,
) -> list[dict]:
    ranked_players = {
        (canonical_person_key(prop.get("player")), str(prop.get("league") or "").strip().upper())
        for prop in ranked_props
    }
    grouped: dict[tuple[str, str], dict] = {}
    for prop in props:
        game = str(prop.get("game") or "").strip()
        sport = str(prop.get("league") or "").strip().upper()
        if not game or not sport:
            continue
        group = grouped.setdefault((sport, group_key(sport, game)), {
            "sport": sport, "game": game, "trending_count": 0, "prop_count": 0, "players": {}, "ranked_players": {},
        })
        player = str(prop.get("player") or "").strip()
        if not player:
            continue
        trend = int(prop.get("trending_count") or 0)
        group["trending_count"] += trend
        group["prop_count"] += 1
        player_row = group["players"].setdefault(
            player, {"player": player, "team": prop.get("team", ""), "trending_count": 0, "ranked": False},
        )
        player_row["trending_count"] += trend
        if (canonical_person_key(player), sport) in ranked_players:
            player_row["ranked"] = True
            group["ranked_players"][player] = player_row
    games = []
    for group in grouped.values():
        players = sorted(group["players"].values(), key=lambda row: row["trending_count"], reverse=True)
        ranked = sorted(group["ranked_players"].values(), key=lambda row: row["trending_count"], reverse=True)
        games.append({
            "sport": group["sport"], "game": group["game"], "trending_count": group["trending_count"],
            "prop_count": group["prop_count"], "ranked_player_count": len(ranked),
            "ranked_players": ranked[:6], "top_players": players[:6],
        })
    games.sort(key=lambda game: (game["ranked_player_count"], game["trending_count"]), reverse=True)
    return games[:limit]
