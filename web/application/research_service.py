from __future__ import annotations

from repository.repositories.research_evidence_repository import ResearchEvidenceRepository

SOURCE_URLS = {
    "ESPN": "https://www.espn.com/",
    "PrizePicks": "https://www.prizepicks.com/",
    "Underdog": "https://underdogfantasy.com/",
    "OpenWeather": "https://openweathermap.org/",
    "NewsAPI": "https://newsapi.org/",
    "EdgeIQ forecast": "",
    "EdgeIQ verified history": "https://www.espn.com/",
}


def persist_player_research(
    payload: dict,
    *,
    availability: dict | None = None,
    game_context: dict | None = None,
) -> dict:
    """Persist current research facts and return a compact, citable memory view."""
    player = str(payload.get("player") or "")
    sport = str(payload.get("sport") or "")
    stat = str(payload.get("stat") or "")
    platform = str(payload.get("platform") or "")
    recommendation = payload.get("recommendation") or {}
    game = str(recommendation.get("game") or "")
    facts: list[dict] = []

    for row in payload.get("chart") or []:
        facts.append(_fact(
            player, sport, stat, platform, str(row.get("game") or game),
            "final_stat", str(row.get("source") or "ESPN"), row, 60 * 24 * 3650,
        ))
    for row in payload.get("active_props") or []:
        source = str(row.get("platform") or platform or "Provider")
        facts.append(_fact(
            player, sport, stat, source, str(row.get("game") or game),
            "provider_market", source, _select(row, (
                "line", "direction", "projection", "confidence", "edge", "game_time",
                "line_offer_type", "payout_multiplier", "provider_backed", "data_strength",
            )), 30,
        ))
    if payload.get("forecast"):
        facts.append(_fact(
            player, sport, stat, platform, game, "probability_forecast", "EdgeIQ forecast",
            payload["forecast"], 240, source_kind="model",
        ))
    role_payload = {
        "starter_split": (payload.get("splits") or {}).get("starter"),
        "bench_split": (payload.get("splits") or {}).get("bench"),
        "teammate_splits": payload.get("teammate_splits") or [],
        "expected_minutes": ((payload.get("forecast") or {}).get("distribution") or {}).get("expected_minutes"),
        "expected_opportunities": ((payload.get("forecast") or {}).get("distribution") or {}).get("expected_opportunities"),
        "live_lineup_confirmed": False,
    }
    if any(value not in (None, "", [], {}) for key, value in role_payload.items() if key != "live_lineup_confirmed"):
        facts.append(_fact(
            player, sport, stat, platform, game, "role_and_lineup", "EdgeIQ verified history",
            role_payload, 240, source_kind="derived_verified_history",
        ))
    if payload.get("closing_lines"):
        facts.append(_fact(
            player, sport, stat, platform, game, "line_movement", platform or "Provider",
            {"closing_lines": payload["closing_lines"]}, 60,
        ))
    if availability:
        facts.append(_fact(
            player, sport, stat, platform, game, "availability", "ESPN/NewsAPI/OpenWeather",
            availability, 30,
        ))
    if game_context:
        facts.append(_fact(
            player, sport, stat, platform, game, "game_context", "EdgeIQ provider context",
            _select(game_context, (
                "game", "sport", "availability", "context_flags", "correlation_note",
            )), 60,
        ))

    written = ResearchEvidenceRepository.record_many(facts)
    memory = ResearchEvidenceRepository.relevant(
        player, stat, sport=sport if sport != "All Sports" else "",
        platform=platform, limit=80,
    )
    return {
        **payload,
        "evidence": memory,
        "evidence_citations": [
            {
                "id": row["id"], "source": row["source"], "source_url": row["source_url"],
                "captured_at": row["captured_at"], "expires_at": row["expires_at"],
                "type": row["type"], "fresh": row["fresh"],
            }
            for row in memory
        ],
        "research_memory": {
            "facts_written_or_reused": len(written),
            "relevant_active_facts": len(memory),
            "outcome_linked_facts": sum(row["outcomes"]["uses"] > 0 for row in memory),
            "cache": "persistent_sql",
        },
        "evidence_coverage": _coverage(memory),
        "evidence_reliability": _reliability(memory),
    }


def research_evidence_payload(
    player: str,
    stat: str = "",
    sport: str = "",
    platform: str = "Both",
    game: str = "",
    include_expired: bool = False,
) -> dict:
    rows = ResearchEvidenceRepository.relevant(
        player, stat, sport=sport, platform=platform, game=game,
        include_expired=include_expired,
    )
    return {
        "player": player,
        "stat": stat,
        "sport": sport or "All Sports",
        "platform": platform,
        "facts": rows,
        "count": len(rows),
        "memory": ResearchEvidenceRepository.summary(),
    }


def _fact(
    player: str,
    sport: str,
    stat: str,
    platform: str,
    game: str,
    evidence_type: str,
    source_name: str,
    payload: dict,
    ttl_minutes: int,
    *,
    source_kind: str = "api",
) -> dict:
    source_root = source_name.split("/", 1)[0]
    return {
        "player": player, "sport": sport, "stat": stat, "platform": platform, "game": game,
        "evidence_type": evidence_type, "source_name": source_name,
        "source_url": SOURCE_URLS.get(source_root, ""), "source_kind": source_kind,
        "payload": payload, "ttl_minutes": ttl_minutes,
    }


def _select(row: dict, keys: tuple[str, ...]) -> dict:
    return {key: row.get(key) for key in keys if row.get(key) not in (None, "", [], {})}


def _coverage(rows: list[dict]) -> dict:
    types = {row["type"] for row in rows if row.get("fresh")}
    expected = {
        "game_logs": "final_stat",
        "provider_market": "provider_market",
        "probability_distribution": "probability_forecast",
        "line_movement": "line_movement",
        "injury_news_weather": "availability",
        "minutes_usage_role": "role_and_lineup",
    }
    available = {label: evidence_type in types for label, evidence_type in expected.items()}
    return {
        "available": available,
        "missing": [label for label, present in available.items() if not present],
        "live_lineup_confirmed": False,
        "note": "Live lineup status remains unknown unless a connected provider explicitly confirms it.",
    }


def _reliability(rows: list[dict]) -> list[dict]:
    grouped: dict[str, dict[str, float]] = {}
    for row in rows:
        bucket = grouped.setdefault(row["type"], {"uses": 0, "wins": 0, "losses": 0})
        outcomes = row.get("outcomes") or {}
        bucket["uses"] += int(outcomes.get("uses") or 0)
        bucket["wins"] += int(outcomes.get("wins") or 0)
        bucket["losses"] += int(outcomes.get("losses") or 0)
    result = []
    for evidence_type, totals in sorted(grouped.items()):
        decisions = int(totals["wins"] + totals["losses"])
        result.append({
            "type": evidence_type,
            "uses": int(totals["uses"]),
            "decisions": decisions,
            "smoothed_win_rate": round((totals["wins"] + 1) / (decisions + 2) * 100.0, 2),
            "eligible_for_model_weight": decisions >= 20,
        })
    return result
