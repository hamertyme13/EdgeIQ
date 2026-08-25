from __future__ import annotations

import os
from pathlib import Path


def deploy_readiness_payload(static_dir: Path, asset_version: str) -> dict:
    database_url = os.getenv("DATABASE_URL", "sqlite:///edgeiq.db")
    allowed_origins = os.getenv("EDGEIQ_ALLOWED_ORIGINS", "").strip()
    configured_mode = os.getenv("EDGEIQ_DEPLOYMENT_MODE", "auto").strip().lower()
    hosted = configured_mode == "hosted" or (
        configured_mode != "local"
        and (not database_url.startswith("sqlite") or bool(allowed_origins))
    )
    mode = "hosted" if hosted else "local"
    checks = [
        _readiness_check("PWA manifest", (static_dir / "manifest.webmanifest").exists(), "Phone install metadata is present."),
        _readiness_check("Service worker", (static_dir / "sw.js").exists(), "Offline app shell support is present."),
        _readiness_check("Static asset version", bool(asset_version), f"Current asset version {asset_version}."),
        _readiness_check(
            "App database" if not hosted else "Production database",
            not hosted or not database_url.startswith("sqlite"),
            (
                "Local SQLite storage is ready. A hosted SQL database is only needed for multi-device sync."
                if not hosted
                else "Set DATABASE_URL to Postgres or another hosted SQL database."
            ),
            status="local ready" if not hosted else None,
        ),
        _readiness_check(
            "Allowed origins",
            bool(allowed_origins),
            (
                "Not required while EdgeIQ runs only on this device."
                if not hosted
                else "Set EDGEIQ_ALLOWED_ORIGINS to the hosted app domain."
            ),
            required=hosted,
            status="local only" if not hosted else None,
        ),
        _readiness_check(
            "OpenAI key",
            bool(os.getenv("OPENAI_API_KEY")),
            "Optional. Adds enhanced screenshot and language review.",
            required=False,
        ),
        _readiness_check("Final stat provider", True, "Official ESPN box scores grade every prop allowed onto the board."),
        _readiness_check(
            "Alert webhook",
            bool(os.getenv("EDGEIQ_ALERT_WEBHOOK_URL")),
            "Optional. Connect a webhook only when external alerts are wanted.",
            required=False,
        ),
    ]
    required_checks = [check for check in checks if check["required"]]
    passed = sum(1 for check in required_checks if check["ok"])
    score = round((passed / len(required_checks)) * 100, 1) if required_checks else 100.0
    ready = all(check["ok"] for check in required_checks)
    return {
        "mode": mode,
        "score": score,
        "status": f"{mode} ready" if ready else f"{mode} needs setup",
        "checks": checks,
        "next_steps": [
            check["action"]
            for check in checks
            if check["required"] and not check["ok"]
        ][:5],
    }


def _readiness_check(
    label: str,
    ok: bool,
    action: str,
    *,
    required: bool = True,
    status: str | None = None,
) -> dict:
    resolved_status = status or ("pass" if ok else "needs setup" if required else "optional")
    return {
        "label": label,
        "ok": bool(ok),
        "required": required,
        "status": resolved_status,
        "action": action,
    }


def sportsbook_integrations_payload() -> dict:
    bet_file = os.getenv("EDGEIQ_BET_HISTORY_FILE", "").strip()
    final_stats_file = os.getenv("EDGEIQ_FINAL_STATS_FILE", "").strip()
    odds_connected = bool(os.getenv("ODDS_API_KEY", "").strip())
    import_ready = bool(bet_file or final_stats_file)
    connected = odds_connected
    connectors = [
        {
            "name": "The Odds API",
            "status": "configured" if odds_connected else "not_configured",
            "capabilities": (
                [
                    "multi-book player prop odds",
                    "exact-line no-vig probability",
                    "PrizePicks/Underdog DFS offer evidence",
                    "quota-aware cached refresh",
                ]
                if odds_connected
                else ["game and player market odds"]
            ),
            "missing": [] if odds_connected else ["Set ODDS_API_KEY to enable live market consensus."],
        },
        {
            "name": "PrizePicks",
            "status": "manual_handoff",
            "capabilities": ["provider lines", "copy slip", "screenshot/file import", "manual result recheck"],
            "missing": ["read-only account sync", "official slip deep link"],
        },
        {
            "name": "Underdog",
            "status": "manual_handoff",
            "capabilities": ["provider lines", "copy slip", "screenshot/file import", "manual result recheck"],
            "missing": ["read-only account sync", "official slip deep link"],
        },
        {
            "name": "DraftKings Pick6",
            "status": "manual_import",
            "capabilities": ["manual entry builder", "copy slip", "screenshot/file import", "ESPN final-stat tracking"],
            "missing": ["verified live Pick6 offer feed", "provider-specific payout feed", "read-only account sync"],
        },
        {
            "name": "Local Imports",
            "status": "configured" if import_ready else "not_configured",
            "capabilities": ["CSV/JSON betting history import", "final-stat file import"] if import_ready else ["CSV/JSON upload inside Tools"],
            "missing": [] if import_ready else ["Set EDGEIQ_BET_HISTORY_FILE or EDGEIQ_FINAL_STATS_FILE for scheduled sync."],
        },
    ]
    return {
        "connected": connected,
        "market_data_connected": odds_connected,
        "import_ready": import_ready,
        "connectors": connectors,
        "headline": (
            "Multi-book market data connected; provider account handoff remains manual."
            if odds_connected
            else "Manual handoff active; multi-book market data is not connected."
        ),
        "next_step": (
            "Review exact-line book count and freshness before using market probability."
            if odds_connected
            else "Configured import files will be synced by Run Sync."
            if import_ready
            else "Use screenshot/CSV upload now; official read-only provider sync can plug into this connector layer later."
        ),
        "privacy_note": "EdgeIQ does not store sportsbook credentials or place entries automatically.",
    }



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
