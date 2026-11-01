"""On-demand NBA points explanations from fixed research facts."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from urllib.parse import urlsplit

from services.ollama_client import ollama_enabled, ollama_role_model, ollama_structured


def _official_game_links(rows: object) -> list[dict[str, str]]:
    """Expose only exact official-game links carried by verified team evidence."""
    if not isinstance(rows, list):
        return []
    links: list[dict[str, str]] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        url = str(row.get("url") or "")
        if len(url) > 250:
            continue
        try:
            parsed = urlsplit(url)
        except ValueError:
            continue
        if (parsed.scheme != "https" or parsed.netloc != "www.espn.com"
                or parsed.query or parsed.fragment
                or not re.fullmatch(r"/game/_/gameId/[A-Za-z0-9-]+", parsed.path)
                or url in seen):
            continue
        seen.add(url)
        links.append({"label": f"ESPN game {len(links) + 1}", "url": url})
        if len(links) == 3:
            break
    return links


def build_nba_points_explanation(
    player: str,
    line: float,
    platform: str,
    detail: str,
    *,
    research: Callable[[str, str, str, str, float], dict],
    prioritize: Callable[[list[dict]], list[str] | None] | None = None,
) -> dict:
    if detail not in {"concise", "detailed"}:
        raise ValueError("Choose a concise or detailed explanation.")
    payload = research(player, "Points", "NBA", platform, line)
    intelligence = payload.get("nba_points_intelligence") or {}
    if not intelligence or payload.get("line") != line:
        return {"status": "unavailable", "reason": "NBA points research is unavailable for this exact line."}

    verified = (intelligence.get("thresholds") or {}).get("verified_season") or {}
    games = int(verified.get("games") or 0)
    custom = verified.get("custom_line") or {}
    projection = intelligence.get("projection") or {}
    reliability = intelligence.get("data_reliability") or {}
    accepted_sources = reliability.get("accepted_sources") or {}
    final_sources = ", ".join(sorted(accepted_sources)) or "Verified final-stat records"
    facts = [
        {"id": "history", "text": f"{games} verified regular-season points games are available for {player}.", "weight": 1,
         "evidence": final_sources},
    ]
    if custom.get("decisions"):
        facts.append({
            "id": "hit_rate",
            "text": (
                f"Over {line:g} points hit in {custom['hits']} of {custom['decisions']} decided "
                f"regular-season games; {custom.get('pushes') or 0} pushed. This is past frequency, not the next-game probability."
            ),
            "weight": 2,
            "evidence": final_sources,
        })
    if projection.get("source") == "verified_history_distribution" and projection.get("expected_points") is not None:
        facts.append({
            "id": "forecast",
            "text": f"EdgeIQ's separate points forecast is {float(projection['expected_points']):g}; its model probability is not the historical hit rate.",
            "weight": 3,
            "evidence": f"EdgeIQ forecast {projection.get('model_version') or 'version unavailable'}",
        })
    else:
        facts.append({
            "id": "forecast",
            "text": "An independent points forecast is unavailable; the entered line is only a market reference.",
            "weight": 3,
            "evidence": "NBA Points research eligibility check",
        })
    matchup = intelligence.get("matchup") or {}
    defense = matchup.get("team_points_allowed") or {}
    team_links = _official_game_links(defense.get("source_games"))
    if matchup.get("opponent") and defense.get("sample_size"):
        facts.append({
            "id": "defense",
            "text": (
                f"Against {matchup['opponent']}, verified pregame team finals show "
                f"{defense['last_10']:g} points allowed on average over the recent sample. "
                "This is team-level context, not a player matchup adjustment."
            ),
            "weight": 4,
            "evidence": "Verified pregame team finals",
            "source_links": team_links,
        })
    if matchup.get("opponent") and (defense.get("home_sample_size") or defense.get("away_sample_size")):
        home_games = min(10, int(defense.get("home_sample_size") or 0))
        away_games = min(10, int(defense.get("away_sample_size") or 0))
        home = (f"{defense['home_points_allowed_last_10']:g} points allowed in "
                f"{home_games} home game{'s' if home_games != 1 else ''}") if home_games else "home split unavailable"
        away = (f"{defense['away_points_allowed_last_10']:g} points allowed in "
                f"{away_games} away game{'s' if away_games != 1 else ''}") if away_games else "away split unavailable"
        rest = (f"{int(defense['days_rest'])} full days of rest" if defense.get("days_rest") is not None
                else "rest unavailable")
        facts.append({
            "id": "location_and_rest",
            "text": f"{matchup['opponent']} has {home}, {away}, and {rest} before this game. These are team-level context, not a points-prop probability.",
            "weight": 4,
            "evidence": "Official pregame NBA regular-season team finals",
            "source_links": team_links,
        })
    if (matchup.get("opponent") and defense.get("defensive_rank") is not None
            and defense.get("advantage_score") is not None and defense.get("ranked_teams")):
        facts.append({
            "id": "defense_rank",
            "text": (
                f"{matchup['opponent']} ranks {int(defense['defensive_rank'])} of {int(defense['ranked_teams'])} "
                f"qualifying NBA teams in recent points allowed (1 allows the fewest). "
                f"The {int(defense['advantage_score'])}/100 matchup indicator is a team-defense percentile, "
                "not this player's chance of exceeding the line."
            ),
            "weight": 4,
            "evidence": "Official pregame NBA team finals; at least five games per qualifying team",
            "source_links": team_links,
        })
    if matchup.get("opponent") and defense.get("pace_sample_size") and defense.get("pace_last_5") is not None:
        facts.append({
            "id": "pace",
            "text": (
                f"Recent games involving {matchup['opponent']} averaged {defense['pace_last_5']:g} estimated "
                f"possessions per regulation game across {min(5, defense['pace_sample_size'])} official box scores. "
                "This is game context, not a player points adjustment."
            ),
            "weight": 4,
            "evidence": "ESPN official team box scores",
            "source_links": team_links,
        })
    facts.append({
        "id": "market",
        "text": "An exact sportsbook payout and validated expected value are unavailable in this research view.",
        "weight": 5,
        "evidence": "Exact-price evidence check",
    })
    ordered_ids = [str(fact["id"]) for fact in facts]
    ranked = (prioritize(facts) if prioritize is not None else _ollama_priorities(facts)) if detail == "detailed" else None
    if ranked and len(set(ranked)) == len(ranked) and set(ranked) == set(ordered_ids):
        ordered_ids = ranked
        source = "ollama_prioritized"
    else:
        source = "deterministic_fallback"
    by_id = {fact["id"]: fact for fact in facts}
    # Ollama can order facts, but it cannot omit the three essential distinctions.
    selected = (["hit_rate" if "hit_rate" in by_id else "history", "forecast", "market"]
                if detail == "concise" else ordered_ids)
    if detail == "detailed" and "market" not in selected:
        selected.append("market")
    return {
        "status": "research_only",
        "source": source,
        "detail": detail,
        "player": player,
        "line": line,
        "bullets": [by_id[key]["text"] for key in selected],
        "fact_details": [
            {"id": key, "text": by_id[key]["text"], "evidence": by_id[key]["evidence"],
             "source_links": by_id[key].get("source_links", [])}
            for key in selected
        ],
        "model_changed": False,
    }


def _ollama_priorities(facts: list[dict]) -> list[str] | None:
    if not ollama_enabled():
        return None
    ids = [fact["id"] for fact in facts]
    schema = {
        "type": "object",
        "properties": {"ordered_ids": {"type": "array", "items": {"type": "string", "enum": ids}}},
        "required": ["ordered_ids"],
    }
    result, _ = ollama_structured(
        [
            {"role": "system", "content": "Rank the supplied verified fact IDs by relevance. Return every ID once. Do not write claims or recalculate values."},
            {"role": "user", "content": json.dumps(facts)},
        ],
        schema,
        model=ollama_role_model("analyst"),
        timeout=8,
    )
    return result.get("ordered_ids") if isinstance(result, dict) else None
