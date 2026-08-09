from __future__ import annotations

from collections.abc import Callable

from web.schemas import ProviderWeightsPayload, RefreshSchedulePayload, UserPreferencePayload, WatchlistItemPayload


def sync_payload(
    allow_estimates: bool,
    *,
    classify_economics: Callable[[], dict],
    import_final_stats_file: Callable[[], dict],
    import_bet_history_file: Callable[[], dict],
    auto_check: Callable[[bool], dict],
    refresh_live_stats: Callable[[], dict],
    dashboard: Callable[[], dict],
) -> dict:
    return {
        "default_wagers": classify_economics(),
        "final_stats_file": import_final_stats_file(),
        "bet_history_file": import_bet_history_file(),
        "auto_check": auto_check(allow_estimates),
        "live_stats": refresh_live_stats(),
        "dashboard": dashboard(),
        "sportsbook_sync": {
            "connected": False,
            "message": (
                "Direct sportsbook account sync is not configured. EdgeIQ synced provider "
                "stats and configured import files."
            ),
        },
    }


def update_dnp_payload(mode: str, *, save_setting: Callable[[str, str], object]) -> dict:
    save_setting("dnp_handling", mode)
    return {"mode": mode}


def update_preferences_payload(
    payload: UserPreferencePayload,
    *,
    save_setting: Callable[[str, str], object],
    serialize: Callable[[object], str],
) -> dict:
    preferences = payload.model_dump()
    save_setting("user_preferences", serialize(preferences))
    return {"preferences": preferences}


def update_provider_weights_payload(
    payload: ProviderWeightsPayload,
    *,
    current_weights: Callable[[], dict],
    save_setting: Callable[[str, str], object],
    serialize: Callable[[object], str],
) -> dict:
    weights = {key: max(0.0, min(2.0, float(value))) for key, value in payload.weights.items() if str(key).strip()}
    merged = {**current_weights(), **weights}
    save_setting("provider_weights", serialize(merged))
    return {"weights": merged}


def update_refresh_schedule_payload(
    payload: RefreshSchedulePayload,
    *,
    save_setting: Callable[[str, str], object],
    serialize: Callable[[object], str],
) -> dict:
    schedule = payload.model_dump()
    save_setting("refresh_schedule", serialize(schedule))
    return {"schedule": schedule}


def run_daily_refresh_payload(
    *,
    run_sync: Callable[[], dict],
    now: Callable[[], object],
    iso_time: Callable[[object], str],
    save_setting: Callable[[str, str], object],
    user_preferences: Callable[[], dict],
    run_scan: Callable[[str, str | None, dict], dict],
    refresh_schedule: Callable[[], dict],
) -> dict:
    result = run_sync()
    ran_at = now()
    save_setting("last_daily_refresh", iso_time(ran_at))
    preferences = user_preferences()
    platform = str(preferences.get("default_platform") or "PrizePicks")
    sport = str(preferences.get("default_sport") or "All Sports")
    sport_filter = None if sport == "All Sports" else sport.upper()
    scan = run_scan(platform, sport_filter, result)
    return {
        "ran_at": iso_time(ran_at),
        "result": result,
        "schedule": refresh_schedule(),
        "daily_briefing": scan.get("cache", {}),
        "scan": scan,
    }


def watchlist_payload(
    *,
    load_items: Callable[[], list[dict]],
    build_alerts: Callable[[list[dict] | None], list[dict]],
) -> dict:
    return {"items": load_items(), "alerts": build_alerts(None)}


def save_watchlist_payload(
    payload: WatchlistItemPayload,
    *,
    item_id: Callable[[dict], str],
    load_items: Callable[[], list[dict]],
    save_items: Callable[[list[dict]], object],
    build_alerts: Callable[[list[dict] | None], list[dict]],
) -> dict:
    item = payload.model_dump()
    item["id"] = item_id(item)
    items = [row for row in load_items() if row.get("id") != item["id"]]
    items.append(item)
    save_items(items)
    return {"items": items, "alerts": build_alerts(items)}


def delete_watchlist_payload(
    item_id: str,
    *,
    load_items: Callable[[], list[dict]],
    save_items: Callable[[list[dict]], object],
    build_alerts: Callable[[list[dict] | None], list[dict]],
) -> dict:
    items = [row for row in load_items() if row.get("id") != item_id]
    save_items(items)
    return {"items": items, "alerts": build_alerts(items)}


def watchlist_alerts_payload(*, build_alerts: Callable[[list[dict] | None], list[dict]]) -> dict:
    alerts = build_alerts(None)
    return {"alerts": alerts, "count": len(alerts)}
