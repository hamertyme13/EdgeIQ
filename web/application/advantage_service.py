from __future__ import annotations

from collections.abc import Callable

from utils.entity_normalization import canonical_matchup_key
from utils.time import iso_utc, utc_now


def advantage_center_payload(
    platform: str,
    sport_filter: str | None,
    *,
    command_center: Callable[[str, str | None], dict],
    clv_report: Callable[[], dict],
    data_health: Callable[[], dict],
    personal_profile: Callable[[], dict],
    watchlist_alerts: Callable[[], list[dict]],
    line_shop_summary: Callable[[list[dict]], dict],
    sportsbook_integrations: Callable[[], dict],
    bankroll_strategy: Callable[[], dict],
) -> dict:
    command = command_center(platform, sport_filter)
    clv = clv_report()
    health = data_health()
    profile = personal_profile()
    watch = watchlist_alerts()
    top_card = command["cards"][0] if command.get("cards") else None
    opportunity_cards = list(command.get("cards", []))
    if command.get("ranked_props"):
        opportunity_cards.append({"score": 0.0, "props": command["ranked_props"]})
    command_opportunities = _command_opportunities(opportunity_cards)
    selected_providers = {"PrizePicks", "Underdog"} if platform == "Both" else {platform}
    return {
        "as_of": iso_utc(utc_now()),
        "platform": platform,
        "sport": sport_filter or "All Sports",
        "top_recommendation": top_card,
        "data_freshness": {
            "as_of": command.get("as_of"),
            "providers": [
                row for row in health.get("providers", []) if row.get("name") in selected_providers
            ],
        },
        "trust_score": top_card.get("trust") if top_card else {"score": 0, "label": "No board"},
        "best_line_finder": (
            line_shop_summary(top_card.get("props", []))
            if top_card
            else {"checked": 0, "legs": []}
        ),
        "closing_line_value": {
            "average_clv": clv.get("average_clv", 0.0),
            "positive_clv_rate": clv.get("positive_clv_rate", 0.0),
            "tracked_legs": clv.get("tracked_legs", 0),
            "quarantined_legs": clv.get("quarantined_legs", 0),
        },
        "personal_profile": profile,
        "watchlist_alerts": watch[:5],
        "timing_alerts": _command_timing_alerts(command.get("cards", [])),
        "opportunity_feed": command_opportunities,
        "sportsbook_integrations": sportsbook_integrations(),
        "bankroll_strategy": bankroll_strategy(),
        "game_contexts": _command_game_contexts(command_opportunities),
        "competitive_features": [
            {"name": "Best Line Finder", "status": "active"},
            {"name": "Closing Line Value", "status": "active"},
            {"name": "Personal Model Profile", "status": "active"},
            {"name": "Prop Watchlist", "status": "active"},
            {"name": "Live Edge Decay", "status": "active"},
            {"name": "Explainable Cards", "status": "active"},
            {"name": "Game Environment", "status": "active"},
            {"name": "Bankroll Modes", "status": "active"},
            {"name": "Promo Boost Analyzer", "status": "active"},
            {"name": "Recommendation Trust Score", "status": "active"},
        ],
    }


def _command_opportunities(cards: list[dict], limit: int = 6) -> list[dict]:
    opportunities: list[dict] = []
    seen: set[tuple[str, str, str]] = set()
    for card in cards:
        for prop in card.get("props", []):
            key = (
                str(prop.get("player", "")).strip().casefold(),
                str(prop.get("stat", "")).strip().casefold(),
                str(prop.get("platform", "")).strip().casefold(),
            )
            if not key[0] or key in seen:
                continue
            seen.add(key)
            opportunities.append({
                "type": "Ranked",
                "action": "Review evidence",
                "priority_score": float(card.get("score") or prop.get("confidence") or 0.0),
                **prop,
            })
            if len(opportunities) >= limit:
                return opportunities
    return opportunities


def _command_timing_alerts(cards: list[dict], limit: int = 5) -> list[dict]:
    alerts = []
    for card in cards:
        timing = card.get("timing") or {}
        if not timing:
            continue
        alerts.append({
            "type": timing.get("label", "Monitor"),
            "action": "Review current line",
            "priority_score": timing.get("score", 0.0),
            "reason": " ".join(timing.get("notes", [])[:2]) or "No urgent timing signal.",
        })
    return alerts[:limit]


def _command_game_contexts(opportunities: list[dict], limit: int = 3) -> list[dict]:
    grouped: dict[tuple[str, str], list[dict]] = {}
    for prop in opportunities:
        game = str(prop.get("game", "")).strip()
        sport = str(prop.get("sport") or prop.get("league") or "").strip().upper()
        if game:
            grouped.setdefault((sport, canonical_matchup_key(game)), []).append(prop)
    return [
        {
            "game": props[0].get("game", ""),
            "sport": sport,
            "prop_count": len(props),
            "ranked_players": props,
            "context_flags": ["Open the matchup for live availability and weather context."],
        }
        for (sport, _), props in list(grouped.items())[:limit]
    ]


def advantage_game_contexts(
    platform: str,
    sport_filter: str | None,
    fetch_props: Callable[[str, str | None], list[dict]],
    build_context: Callable[[str, str | None, str], dict],
    limit: int = 3,
) -> list[dict]:
    props = fetch_props(platform, sport_filter)
    props.sort(key=lambda row: int(row.get("trending_count") or 0), reverse=True)
    games: list[dict] = []
    seen: set[str] = set()
    for prop in props:
        game = str(prop.get("game", "")).strip()
        canonical_game = canonical_matchup_key(game.replace("-", "@"))
        if not canonical_game or canonical_game in seen:
            continue
        seen.add(canonical_game)
        games.append(build_context(game, sport_filter or prop.get("league", ""), platform))
        if len(games) >= limit:
            break
    return games
