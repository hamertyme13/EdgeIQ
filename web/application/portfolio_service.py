from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from utils.entity_normalization import canonical_matchup_key, canonical_person_key
from utils.stat_normalization import stat_type_from_text
from web.schemas import BetPayload


def refresh_portfolio_market_payload(
    *,
    pending_entries: list[dict],
    fetch_platform_props: Callable[..., list[dict]],
    intelligence: Callable[[], dict],
) -> dict:
    """Refresh only the books represented by pending paid entries."""
    real_entries = [
        entry for entry in pending_entries
        if str(entry.get("entry_mode") or "real").lower() == "real"
    ]
    platforms = sorted({
        str(prop.get("platform") or entry.get("platform") or "").strip()
        for entry in real_entries
        for prop in (entry.get("props") or [{}])
        if str(prop.get("platform") or entry.get("platform") or "").strip()
    })
    provider_results = []
    for platform in platforms:
        try:
            props = fetch_platform_props(platform, force_refresh=True)
            provider_results.append({
                "platform": platform,
                "status": "refreshed" if props else "no_current_lines",
                "props_received": len(props),
                "message": (
                    f"Loaded {len(props)} current {platform} lines."
                    if props else f"{platform} returned no trackable current lines."
                ),
            })
        except Exception as exc:
            provider_results.append({
                "platform": platform,
                "status": "failed",
                "props_received": 0,
                "message": f"{platform} did not respond. Try again shortly.",
                "error_type": exc.__class__.__name__,
            })

    refreshed = sum(1 for row in provider_results if row["status"] == "refreshed")
    payload = intelligence()
    remaining = int((payload.get("monitor") or {}).get("status_counts", {}).get("Needs Refresh", 0))
    if not real_entries:
        message = "There are no pending paid entries to refresh."
    elif not platforms:
        message = "Pending paid entries do not contain a recognizable provider."
    elif remaining:
        message = (
            f"Refreshed {refreshed}/{len(platforms)} provider feeds. "
            f"{remaining} entr{'y still needs' if remaining == 1 else 'ies still need'} an exact same-game line match."
        )
    else:
        message = f"Refreshed {refreshed}/{len(platforms)} provider feeds. Portfolio lines are current."
    return {
        "refreshed_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "pending_paid_entries": len(real_entries),
        "providers": provider_results,
        "message": message,
        "intelligence": payload,
    }


def portfolio_intelligence_payload(
    *,
    pending_entries: list[dict],
    bankroll: float,
    strategy: dict,
) -> dict:
    real_entries = [
        entry for entry in pending_entries
        if str(entry.get("entry_mode") or "real").lower() == "real"
    ]
    counts = _portfolio_counts(real_entries)
    limits = _portfolio_limits(strategy)
    wager = round(sum(float(entry.get("wager") or 0.0) for entry in real_entries), 2)
    exposure_pct = round(wager / bankroll * 100.0, 1) if bankroll > 0 else 0.0
    concentrations = _portfolio_concentrations(counts, limits, bankroll)
    shared_markets = [row for row in counts["market"].values() if int(row["entries"]) > 1]
    correlation_score = min(100, sum(int(row["entries"]) - 1 for row in shared_markets) * 22 + sum(
        max(0, int(row["entries"]) - 1) for row in counts["game"].values()
    ) * 8)
    concentration_score = max(0, 100 - sum(item["penalty"] for item in concentrations))
    if any(item["severity"] == "danger" for item in concentrations):
        status = "Concentrated"
    elif concentrations:
        status = "Watch"
    else:
        status = "Balanced"
    return {
        "status": status,
        "score": concentration_score,
        "pending_real_entries": len(real_entries),
        "pending_paper_entries": sum(
            1 for entry in pending_entries
            if str(entry.get("entry_mode") or "real").lower() == "paper"
        ),
        "open_wager": wager,
        "bankroll": round(bankroll, 2),
        "bankroll_exposure_pct": exposure_pct,
        "limits": limits,
        "concentrations": concentrations,
        "correlation_score": correlation_score,
        "shared_leg_failure_risk": {
            "repeated_props": len(shared_markets),
            "exposed_wager": round(sum(float(row["wager"]) for row in shared_markets), 2),
            "message": (
                f"{len(shared_markets)} exact prop{'s appear' if len(shared_markets) != 1 else ' appears'} on multiple pending entries."
                if shared_markets else "No exact prop is repeated across pending paid entries."
            ),
        },
        "top_players": _top_exposures(counts["player"], 6),
        "top_games": _top_exposures(counts["game"], 5),
        "top_teams": _top_exposures(counts["team"], 6),
        "top_markets": _top_exposures(counts["market"], 6),
        "top_stats": _top_exposures(counts["stat"], 5),
        "directions": _top_exposures(counts["direction"], 2),
        "providers": _top_exposures(counts["provider"], 5),
    }


def active_portfolio_monitor_payload(
    *,
    pending_entries: list[dict],
    market_entries: list[dict],
    now: datetime | None = None,
) -> dict:
    """Summarize post-placement line value and timing for pending paid entries."""
    checked_at = (now or datetime.now(UTC)).astimezone(UTC)
    market_by_id = {
        int(entry.get("id") or 0): entry
        for entry in market_entries
        if entry.get("id")
    }
    monitored = []
    for entry in pending_entries:
        if str(entry.get("entry_mode") or "real").lower() != "real":
            continue
        monitored.append(_monitored_entry(entry, market_by_id.get(int(entry.get("id") or 0), {}), checked_at))

    monitored.sort(key=lambda row: (int(row["priority"]), float(row["wager"])), reverse=True)
    statuses = _status_counts(monitored)
    review_count = statuses.get("Review", 0)
    watch_count = statuses.get("Watch", 0)
    refresh_count = statuses.get("Needs Refresh", 0)
    return {
        "checked_at": checked_at.isoformat().replace("+00:00", "Z"),
        "entries": monitored,
        "count": len(monitored),
        "status_counts": statuses,
        "action_count": review_count + watch_count + refresh_count,
        "headline": (
            f"{review_count} paid entr{'y needs' if review_count == 1 else 'ies need'} review."
            if review_count
            else f"{watch_count} paid entr{'y is' if watch_count == 1 else 'ies are'} on watch."
            if watch_count
            else f"Refresh market data for {refresh_count} paid entr{'y' if refresh_count == 1 else 'ies'}."
            if refresh_count
            else "Pending paid entries are holding their recorded line value."
            if monitored
            else "No paid entries are currently pending."
        ),
    }


def _monitored_entry(entry: dict, market_entry: dict, now: datetime) -> dict:
    market_legs = market_entry.get("legs") or []
    props = entry.get("props") or []
    legs = [
        _monitored_leg(prop, market_legs[index] if index < len(market_legs) else {}, now)
        for index, prop in enumerate(props)
    ]
    known = [float(leg["line_value"]) for leg in legs if leg.get("line_value") is not None]
    adverse = sum(1 for value in known if value < 0)
    favorable = sum(1 for value in known if value > 0)
    unavailable = len(legs) - len(known)
    locked = bool(legs) and all(leg["game_state"] in {"Live", "Final", "Awaiting Result"} for leg in legs)
    average = round(sum(known) / len(known), 2) if known else None

    if locked:
        status, priority = "Locked", 40
        action = "The card is underway or complete. Track settlement and avoid duplicating this exposure."
    elif adverse >= max(2, (len(legs) + 1) // 2) or (average is not None and average <= -1.0):
        status, priority = "Review", 90
        action = "Several legs moved against the placed lines. Recheck availability and avoid adding similar exposure."
    elif adverse:
        status, priority = "Watch", 70
        action = "At least one leg moved against the placed line. Monitor it before adding another related entry."
    elif unavailable:
        status, priority = "Needs Refresh", 55
        action = "Current same-game line history is incomplete. Refresh provider data before drawing a conclusion."
    else:
        status, priority = "Holding Value", 25
        action = "The latest recorded lines have not moved against this card. Continue normal monitoring."

    return {
        "id": int(entry.get("id") or 0),
        "platform": str(entry.get("platform") or "Unknown provider"),
        "wager": round(float(entry.get("wager") or 0.0), 2),
        "placed_at": _iso_datetime(entry.get("placed_at")),
        "status": status,
        "priority": priority,
        "action": action,
        "average_line_value": average,
        "favorable_legs": favorable,
        "adverse_legs": adverse,
        "unavailable_legs": unavailable,
        "legs": legs,
    }


def _monitored_leg(prop: dict, market_leg: dict, now: datetime) -> dict:
    placed_line = float(prop.get("line") or market_leg.get("placed_line") or 0.0)
    current_line = market_leg.get("current_line")
    line_value = market_leg.get("clv")
    game_time = _datetime_value(prop.get("game_time"))
    if game_time is None or now < game_time:
        game_state = "Pregame"
    elif prop.get("actual") is not None or prop.get("final_result"):
        game_state = "Awaiting Result" if not prop.get("final_result") else "Final"
    else:
        game_state = "Live"
    movement_status = (
        "Favorable" if line_value is not None and float(line_value) > 0
        else "Adverse" if line_value is not None and float(line_value) < 0
        else "Flat" if line_value is not None
        else "Unavailable"
    )
    return {
        "player": str(prop.get("player") or market_leg.get("player") or "Unknown player"),
        "stat": str(prop.get("stat") or market_leg.get("stat") or "Prop"),
        "direction": str(prop.get("direction") or "Over").title(),
        "placed_line": placed_line,
        "current_line": float(current_line) if current_line is not None else None,
        "line_value": float(line_value) if line_value is not None else None,
        "movement_status": movement_status,
        "game": str(prop.get("game") or ""),
        "game_time": _iso_datetime(prop.get("game_time")),
        "game_state": game_state,
        "reliable": bool(market_leg.get("reliable")),
        "reliability_reason": str(market_leg.get("reliability_reason") or ""),
    }


def _status_counts(entries: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for entry in entries:
        status = str(entry.get("status") or "Unknown")
        counts[status] = counts.get(status, 0) + 1
    return counts


def _datetime_value(value: object) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value or "").strip()
        if not text:
            return None
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _iso_datetime(value: object) -> str:
    parsed = _datetime_value(value)
    return parsed.isoformat().replace("+00:00", "Z") if parsed else ""


def portfolio_ranked_suggestions(
    suggestions: list[dict],
    *,
    pending_entries: list[dict],
    strategy: dict,
    limit: int,
) -> list[dict]:
    limits = _portfolio_limits(strategy)
    real_pending = [
        entry for entry in pending_entries
        if str(entry.get("entry_mode") or "real").lower() == "real"
    ]
    counts = _portfolio_counts(real_pending)
    remaining = [dict(suggestion) for suggestion in suggestions]
    ranked: list[dict] = []
    selected_markets: set[str] = set()
    selected_players: set[str] = set()
    all_props = [
        prop
        for suggestion in suggestions
        for prop in (suggestion.get("entry") or {}).get("props", [])
    ]

    while remaining and len(ranked) < limit:
        assessed = []
        for row in remaining:
            assessment = _portfolio_card_assessment(row, counts, limits)
            props = (row.get("entry") or {}).get("props", [])
            market_keys = {_prop_portfolio_keys(prop)["market"][0] for prop in props}
            player_keys = {_prop_portfolio_keys(prop)["player"][0] for prop in props}
            shared_markets = len((market_keys - {""}) & selected_markets)
            shared_players = len((player_keys - {""}) & selected_players)
            diversity_penalty = shared_markets * 14.0 + shared_players * 4.0
            assessment["batch_shared_legs"] = shared_markets
            assessment["batch_shared_players"] = shared_players
            assessment["batch_diversity_penalty"] = diversity_penalty
            assessment["adjusted_score"] = round(float(assessment["adjusted_score"]) - diversity_penalty, 1)
            assessed.append((assessment, row))
        assessment, chosen = max(
            assessed,
            key=lambda item: (
                float(item[0]["adjusted_score"]),
                float(item[1].get("value_adjusted_score") or item[1].get("score") or 0.0),
            ),
        )
        chosen["portfolio"] = assessment
        chosen["portfolio"]["replacements"] = _portfolio_replacements(
            chosen,
            assessment,
            all_props,
            counts,
            limits,
        )
        ranked.append(chosen)
        for prop in (chosen.get("entry") or {}).get("props", []):
            keys = _prop_portfolio_keys(prop)
            selected_markets.add(keys["market"][0])
            selected_players.add(keys["player"][0])
        remaining.remove(chosen)

    for rank, suggestion in enumerate(ranked, start=1):
        suggestion["rank"] = rank
    return ranked


def _portfolio_card_assessment(suggestion: dict, counts: dict, limits: dict) -> dict:
    props = (suggestion.get("entry") or {}).get("props", [])
    projected = _copy_counts(counts)
    _add_props_to_counts(projected, props, wager=0.0)
    conflicts: list[dict] = []
    penalty = 0.0
    seen_conflicts: set[tuple[str, str]] = set()
    for prop in props:
        keys = _prop_portfolio_keys(prop)
        for dimension, limit_name, weight in (
            ("market", "max_market_entries", 18.0),
            ("player", "max_player_entries", 10.0),
            ("game", "max_game_entries", 6.0),
        ):
            key, label = keys[dimension]
            if not key:
                continue
            projected_count = int(projected[dimension].get(key, {}).get("entries") or 0)
            limit_value = int(limits[limit_name])
            conflict_key = (dimension, key)
            if projected_count <= limit_value or conflict_key in seen_conflicts:
                continue
            seen_conflicts.add(conflict_key)
            excess = projected_count - limit_value
            conflict_penalty = weight * excess
            penalty += conflict_penalty
            conflicts.append({
                "dimension": dimension,
                "key": key,
                "label": label,
                "projected_entries": projected_count,
                "limit": limit_value,
                "penalty": conflict_penalty,
                "message": f"{label} would appear on {projected_count} open entries (limit {limit_value}).",
            })
    base_score = float(suggestion.get("value_adjusted_score") or suggestion.get("score") or 0.0)
    adjusted_score = round(base_score - penalty, 1)
    if any(conflict["dimension"] == "market" for conflict in conflicts):
        risk = "High"
    elif conflicts:
        risk = "Medium"
    else:
        risk = "Low"
    return {
        "risk": risk,
        "base_score": round(base_score, 1),
        "penalty": round(penalty, 1),
        "adjusted_score": adjusted_score,
        "conflicts": conflicts,
        "summary": (
            "No pending concentration limits would be exceeded."
            if not conflicts
            else f"{len(conflicts)} portfolio concentration limit{'s' if len(conflicts) != 1 else ''} would be exceeded."
        ),
    }


def _portfolio_replacements(
    suggestion: dict,
    assessment: dict,
    candidates: list[dict],
    counts: dict,
    limits: dict,
) -> list[dict]:
    props = (suggestion.get("entry") or {}).get("props", [])
    current_players = {canonical_person_key(prop.get("player")) for prop in props}
    conflict_players = {
        conflict["key"]
        for conflict in assessment.get("conflicts", [])
        if conflict.get("dimension") == "player"
    }
    conflict_markets = {
        conflict["key"]
        for conflict in assessment.get("conflicts", [])
        if conflict.get("dimension") == "market"
    }
    risky = [
        prop for prop in props
        if _prop_portfolio_keys(prop)["player"][0] in conflict_players
        or _prop_portfolio_keys(prop)["market"][0] in conflict_markets
    ]
    replacements: list[dict] = []
    used: set[str] = set()
    used_players: set[str] = set()
    for prop in risky[:3]:
        original_confidence = float(prop.get("confidence") or 0.0)
        alternatives = []
        for candidate in candidates:
            keys = _prop_portfolio_keys(candidate)
            player_key = keys["player"][0]
            market_key = keys["market"][0]
            game_key = keys["game"][0]
            if not player_key or player_key in current_players or player_key in used_players or market_key in used:
                continue
            if int(counts["market"].get(market_key, {}).get("entries") or 0) >= limits["max_market_entries"]:
                continue
            if int(counts["player"].get(player_key, {}).get("entries") or 0) >= limits["max_player_entries"]:
                continue
            if game_key and int(counts["game"].get(game_key, {}).get("entries") or 0) >= limits["max_game_entries"]:
                continue
            confidence = float(candidate.get("confidence") or 0.0)
            if confidence < original_confidence - 8.0:
                continue
            alternatives.append(candidate)
        if not alternatives:
            continue
        replacement = max(
            alternatives,
            key=lambda row: (float(row.get("confidence") or 0.0), float(row.get("edge") or 0.0)),
        )
        replacement_key = _prop_portfolio_keys(replacement)["market"][0]
        replacement_player = _prop_portfolio_keys(replacement)["player"][0]
        used.add(replacement_key)
        used_players.add(replacement_player)
        replacements.append({
            "remove": _prop_label(prop),
            "remove_prop": prop,
            "add": replacement,
            "message": f"Replace {_prop_label(prop)} with {_prop_label(replacement)} to reduce pending exposure.",
        })
    return replacements


def _portfolio_counts(entries: list[dict]) -> dict[str, dict[str, dict]]:
    counts: dict[str, dict[str, dict]] = {
        dimension: {} for dimension in ("player", "game", "team", "market", "stat", "direction", "provider")
    }
    for entry in entries:
        _add_props_to_counts(counts, entry.get("props") or [], float(entry.get("wager") or 0.0))
    return counts


def _add_props_to_counts(counts: dict, props: list[dict], wager: float) -> None:
    seen: dict[str, set[str]] = {dimension: set() for dimension in counts}
    for prop in props:
        for dimension, (key, label) in _prop_portfolio_keys(prop).items():
            if not key or key in seen[dimension]:
                continue
            seen[dimension].add(key)
            row = counts[dimension].setdefault(key, {"key": key, "label": label, "entries": 0, "wager": 0.0})
            row["entries"] += 1
            row["wager"] = round(float(row["wager"]) + wager, 2)


def _prop_portfolio_keys(prop: dict) -> dict[str, tuple[str, str]]:
    player_key = canonical_person_key(prop.get("player"))
    player = str(prop.get("player") or "Unknown player")
    stat = stat_type_from_text(prop.get("stat", "")).value
    direction = str(prop.get("direction") or "Over").title()
    line = float(prop.get("line") or 0.0)
    game_key = canonical_matchup_key(prop.get("game"))
    game = str(prop.get("game") or "Unknown matchup")
    provider = str(prop.get("platform") or "Unknown provider")
    team = str(prop.get("team") or "Unknown team")
    market_key = f"{player_key}|{stat.casefold()}|{direction.casefold()}|{line:.2f}"
    return {
        "player": (player_key, player),
        "game": (game_key, game),
        "team": (team.casefold(), team),
        "market": (market_key, f"{player} {direction} {stat} {line:g}"),
        "stat": (stat.casefold(), stat),
        "direction": (direction.casefold(), direction),
        "provider": (provider.casefold(), provider),
    }


def _portfolio_limits(strategy: dict) -> dict:
    return {
        "max_player_entries": max(1, int(strategy.get("max_player_entries") or 2)),
        "max_game_entries": max(1, int(strategy.get("max_game_entries") or 3)),
        "max_market_entries": max(1, int(strategy.get("max_market_entries") or 1)),
        "max_open_exposure_pct": float(strategy.get("max_open_exposure_pct") or 15.0),
        "max_player_exposure_pct": float(strategy.get("max_player_exposure_pct") or 7.5),
    }


def _portfolio_concentrations(counts: dict, limits: dict, bankroll: float) -> list[dict]:
    rows: list[dict] = []
    for dimension, limit_name, severity, weight in (
        ("market", "max_market_entries", "danger", 18),
        ("player", "max_player_entries", "warning", 10),
        ("game", "max_game_entries", "warning", 6),
    ):
        limit_value = int(limits[limit_name])
        for exposure in counts[dimension].values():
            if int(exposure["entries"]) <= limit_value:
                continue
            excess = int(exposure["entries"]) - limit_value
            rows.append({
                **exposure,
                "dimension": dimension,
                "limit": limit_value,
                "severity": severity,
                "penalty": weight * excess,
                "message": f"{exposure['label']} appears on {exposure['entries']} pending entries (limit {limit_value}).",
            })
    player_wager_limit = bankroll * float(limits["max_player_exposure_pct"]) / 100.0
    if bankroll > 0:
        for exposure in counts["player"].values():
            if float(exposure["wager"]) <= player_wager_limit:
                continue
            pct = round(float(exposure["wager"]) / bankroll * 100.0, 1)
            rows.append({
                **exposure,
                "dimension": "player_bankroll",
                "limit": limits["max_player_exposure_pct"],
                "severity": "danger",
                "penalty": 18,
                "message": f"{exposure['label']} carries {pct:.1f}% of bankroll exposure (limit {limits['max_player_exposure_pct']:.1f}%).",
            })
    return sorted(rows, key=lambda row: (row["severity"] == "danger", row["entries"]), reverse=True)


def _top_exposures(rows: dict[str, dict], limit: int) -> list[dict]:
    return sorted(rows.values(), key=lambda row: (int(row["entries"]), float(row["wager"])), reverse=True)[:limit]


def _copy_counts(counts: dict) -> dict:
    return {
        dimension: {key: dict(row) for key, row in rows.items()}
        for dimension, rows in counts.items()
    }


def _prop_label(prop: dict) -> str:
    return (
        f"{prop.get('player') or 'Player'} {prop.get('direction') or 'Over'} "
        f"{prop.get('stat') or 'prop'} {float(prop.get('line') or 0.0):g}"
    )


def personal_profile_payload(*, dashboard: Callable[[], dict]) -> dict:
    dashboard_stats = dashboard()
    entry_stats = dashboard_stats.get("entries", {})
    by_sport = dashboard_stats.get("by_sport", {})
    by_platform = dashboard_stats.get("by_platform", {})
    by_stat = dashboard_stats.get("by_stat", {})
    paper = entry_stats.get("paper", {})
    best_sport = _best_group(by_sport)
    best_platform = _best_group(by_platform)
    weak_spot = _worst_group(by_sport)
    return {
        "summary": {
            "record": dashboard_stats.get("record", "0-0"),
            "profit": dashboard_stats.get("profit", 0.0),
            "roi": dashboard_stats.get("roi", 0.0),
            "recommendation_accuracy": dashboard_stats.get("recommendation_accuracy", {}),
            "paper_calibration": paper,
        },
        "strengths": [
            f"{best_sport['name']} is your strongest sport by profit/ROI."
            if best_sport
            else "Settle more entries to identify strongest sport.",
            (
                f"{best_platform['name']} is your best platform so far."
                if best_platform and float(best_platform.get("profit", 0.0)) > 0
                else "No platform is profitable yet; keep platform comparisons in paper or conservative mode."
                if best_platform
                else "Track platform on each entry to find the best app for you."
            ),
        ],
        "weaknesses": [
            f"{weak_spot['name']} is lagging; consider paper-only until calibration improves."
            if weak_spot
            else "No weak segment detected yet.",
        ],
        "by_sport": by_sport,
        "by_platform": by_platform,
        "by_stat": by_stat,
        "recommended_settings": _recommended_user_settings(dashboard_stats, paper),
    }


def bets_payload(
    limit: int,
    entry_limit: int,
    *,
    load_bets: Callable[[], list],
    load_entries: Callable[[], list[dict]],
    serialize_bet: Callable[[object], dict],
    serialize_entry: Callable[[dict, dict[int, dict], dict], dict],
    load_settlement_evidence: Callable[[list[int]], dict[int, dict[int, dict]]],
    load_line_histories: Callable[[list[dict]], dict],
) -> dict:
    bounded_limit = max(1, min(limit, 250))
    bounded_entry_limit = max(1, min(entry_limit, 100))
    all_bets = load_bets()
    settled_entries = [entry for entry in load_entries() if entry.get("status") == "Settled"]
    displayed_entries = settled_entries[:bounded_entry_limit]
    evidence = load_settlement_evidence([int(entry["id"]) for entry in displayed_entries if entry.get("id")])
    histories = load_line_histories([
        prop
        for entry in displayed_entries
        for prop in entry.get("props", [])
    ])
    all_entries = [
        serialize_entry(entry, evidence.get(int(entry.get("id") or 0), {}), histories)
        for entry in displayed_entries
    ]
    return {
        "bets": [serialize_bet(bet) for bet in all_bets[:bounded_limit]],
        "entries": all_entries,
        "summary": {
            "saved_bets": len(all_bets),
            "completed_entries": len(settled_entries),
            "displayed_bets": min(len(all_bets), bounded_limit),
            "displayed_entries": len(all_entries),
        },
    }


def save_bet_payload(
    payload: BetPayload,
    *,
    potential_profit: Callable[[int, float], float],
    create_bet: Callable[[BetPayload, float], object],
    save_bet: Callable[[object], object],
    serialize_bet: Callable[[object], dict],
    dashboard: Callable[[], dict],
) -> dict:
    profit = 0.0
    if payload.result == "Win":
        profit = potential_profit(payload.odds, payload.wager)
    elif payload.result == "Loss":
        profit = -payload.wager
    bet = create_bet(payload, round(profit, 2))
    save_bet(bet)
    return {"bet": serialize_bet(bet), "dashboard": dashboard()}


def _best_group(groups: dict) -> dict | None:
    if not groups:
        return None
    name, stats = max(
        groups.items(),
        key=lambda item: (
            float(item[1].get("profit", 0.0)),
            float(item[1].get("roi", 0.0)),
            int(item[1].get("wins", 0)),
        ),
    )
    return {"name": name, **stats}


def _worst_group(groups: dict) -> dict | None:
    candidates = [
        (name, stats) for name, stats in groups.items() if int(stats.get("wins", 0)) + int(stats.get("losses", 0)) > 0
    ]
    if not candidates:
        return None
    name, stats = min(
        candidates,
        key=lambda item: (
            float(item[1].get("profit", 0.0)),
            float(item[1].get("roi", 0.0)),
        ),
    )
    return {"name": name, **stats}


def _recommended_user_settings(stats: dict, paper: dict) -> dict:
    roi = float(stats.get("roi") or 0.0)
    accuracy = float((stats.get("recommendation_accuracy") or {}).get("accuracy") or 0.0)
    paper_edge = float(paper.get("calibration_edge") or 0.0)
    if roi < 0 or (accuracy and accuracy < 48):
        risk_style = "conservative"
        max_wager_pct = 2.0
    elif roi > 20 and accuracy >= 55 and paper_edge >= -8:
        risk_style = "aggressive"
        max_wager_pct = 7.5
    else:
        risk_style = "balanced"
        max_wager_pct = 5.0
    return {
        "risk_style": risk_style,
        "max_wager_pct": max_wager_pct,
        "paper_first": paper.get("decisions", 0) < 10,
        "note": "Uses your real and paper results to suggest sizing discipline.",
    }
