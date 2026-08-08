from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from utils.time import iso_utc, utc_now

GetSetting = Callable[[str, str], str]
SetSetting = Callable[[str, str], object]


def daily_scan_steps(active: str) -> list[dict]:
    labels = [
        ("scanning_props", "Scanning Props"),
        ("analyzing_games", "Analyzing Games"),
        ("building_entries", "Building Entries"),
        ("ready", "Ready"),
    ]
    order = [key for key, _label in labels]
    active_index = order.index(active) if active in order else -1
    return [
        {
            "key": key,
            "label": label,
            "state": "complete"
            if index < active_index or active == "ready"
            else "active"
            if key == active
            else "pending",
        }
        for index, (key, label) in enumerate(labels)
    ]


def friendly_scan_status(status: str) -> str:
    return {
        "not_run_today": "Not Run Today",
        "scanning_props": "Scanning Props",
        "analyzing_games": "Analyzing Games",
        "building_entries": "Building Entries",
        "ready": "Ready",
        "failed": "Failed",
    }.get(status, status.replace("_", " ").title())


def new_daily_scan(platform: str, sport_filter: str | None, trigger: str = "manual") -> dict:
    started_at = iso_utc(utc_now())
    basis = f"{started_at}:{platform}:{sport_filter or 'All Sports'}:{trigger}"
    return {
        "id": hashlib.sha1(basis.encode("utf-8")).hexdigest()[:12],
        "status": "scanning_props",
        "status_label": "Scanning Props",
        "message": "EdgeIQ is collecting provider lines and current board context.",
        "platform": platform,
        "sport": sport_filter or "All Sports",
        "trigger": trigger,
        "started_at": started_at,
        "updated_at": started_at,
        "completed_at": "",
        "progress": 20,
        "steps": daily_scan_steps("scanning_props"),
        "summary": {},
        "cache": {},
        "errors": [],
    }


def save_daily_scan_status(scan: dict, set_setting: SetSetting, status_key: str) -> dict:
    updated = {**scan, "updated_at": iso_utc(utc_now())}
    set_setting(status_key, json.dumps(updated))
    return updated


def recover_interrupted_daily_scan(
    get_setting: GetSetting,
    save_status: Callable[[dict], dict],
    safe_json_loads: Callable[[str], object],
    status_key: str,
) -> None:
    raw_current = safe_json_loads(get_setting(status_key, ""))
    current = raw_current if isinstance(raw_current, dict) else {}
    if not isinstance(current, dict) or current.get("status") not in {
        "scanning_props",
        "analyzing_games",
        "building_entries",
    }:
        return
    save_status(
        {
            **current,
            "status": "not_run_today",
            "status_label": "Ready to Scan",
            "message": "The previous scan was interrupted when EdgeIQ closed. Start a new scan to refresh today's briefing.",
            "progress": 0,
            "steps": daily_scan_steps(""),
            "completed_at": "",
            "errors": [],
        }
    )


def update_daily_scan(
    scan: dict,
    status: str,
    message: str,
    progress: int,
    save_status: Callable[[dict], dict],
    **extra: object,
) -> dict:
    return save_status(
        {
            **scan,
            **extra,
            "status": status,
            "status_label": friendly_scan_status(status),
            "message": message,
            "progress": progress,
            "steps": daily_scan_steps(status),
        }
    )


def daily_scan_summary(briefing: dict) -> dict:
    sections = briefing.get("sections", {})
    return {
        "headline": briefing.get("headline", ""),
        "analyzed_props": int((briefing.get("summary") or {}).get("analyzed_props") or 0),
        "confirmed_props": int((briefing.get("summary") or {}).get("confirmed_props") or 0),
        "games": len(briefing.get("games_today") or []),
        "bet_cards": len(sections.get("bet") or []),
        "paper_cards": len(sections.get("paper") or []),
        "watch_cards": len(sections.get("watch") or []),
        "avoid_cards": len(sections.get("avoid") or []),
        "risk_level": (briefing.get("summary") or {}).get("risk_level", ""),
        "expected_value": (briefing.get("summary") or {}).get("expected_value", 0.0),
    }


def append_daily_scan_log(
    scan: dict,
    get_setting: GetSetting,
    set_setting: SetSetting,
    safe_json_loads: Callable[[str], object],
    log_key: str,
) -> None:
    raw = safe_json_loads(get_setting(log_key, ""))
    rows = raw.get("runs", []) if isinstance(raw, dict) else []
    rows = [scan, *[row for row in rows if row.get("id") != scan.get("id")]][:20]
    set_setting(log_key, json.dumps({"runs": rows}))


def run_daily_briefing_scan(
    platform: str,
    sport_filter: str | None,
    *,
    scan_id: str | None,
    trigger: str,
    sync_result: dict | None,
    create_scan: Callable[[str, str | None, str], dict],
    save_status: Callable[[dict], dict],
    update_scan: Callable[..., dict],
    cached_briefing: Callable[..., dict],
    append_log: Callable[[dict], None],
) -> dict:
    scan = create_scan(platform, sport_filter, trigger)
    if scan_id:
        scan["id"] = scan_id
    if sync_result:
        scan["sync_result"] = sync_result
    save_status(scan)
    try:
        scan = update_scan(
            scan, "analyzing_games", "EdgeIQ is grouping games, checking injuries, and scoring the board.", 45
        )
        scan = update_scan(scan, "building_entries", "EdgeIQ is building Bet, Paper, Watch, and Avoid cards.", 70)
        briefing = cached_briefing(platform, sport_filter, refresh=True)
        scan = update_scan(
            scan,
            "ready",
            "Today's briefing is ready.",
            100,
            completed_at=iso_utc(utc_now()),
            summary=daily_scan_summary(briefing),
            cache=briefing.get("cache", {}),
            errors=[],
        )
    except Exception:
        scan = update_scan(
            scan,
            "failed",
            "Daily briefing scan failed before the board was ready.",
            100,
            completed_at=iso_utc(utc_now()),
            errors=[
                "Daily Briefing could not finish. Refresh the scan and check provider connections if it happens again."
            ],
        )
    append_log(scan)
    return scan


def daily_scan_status_payload(
    platform: str,
    sport_filter: str | None,
    get_setting: GetSetting,
    safe_json_loads: Callable[[str], object],
    status_key: str,
    log_key: str,
) -> dict:
    raw_current = safe_json_loads(get_setting(status_key, ""))
    current = raw_current if isinstance(raw_current, dict) else {}
    log = safe_json_loads(get_setting(log_key, ""))
    runs = log.get("runs", []) if isinstance(log, dict) else []
    today = utc_now().date()
    if not current:
        current = {
            "id": "",
            "status": "not_run_today",
            "status_label": "Not Run Today",
            "message": "No Daily Briefing scan has run yet today.",
            "platform": platform,
            "sport": sport_filter or "All Sports",
            "started_at": "",
            "updated_at": "",
            "completed_at": "",
            "progress": 0,
            "steps": daily_scan_steps(""),
            "summary": {},
            "cache": {},
            "errors": [],
        }
    elif current.get("completed_at"):
        try:
            completed = datetime.fromisoformat(str(current["completed_at"]).replace("Z", "+00:00"))
            if completed.tzinfo is None:
                completed = completed.replace(tzinfo=UTC)
            if completed.date() != today:
                current = {
                    **current,
                    "status": "not_run_today",
                    "status_label": "Not Run Today",
                    "message": "No Daily Briefing scan has run yet today.",
                    "progress": 0,
                    "steps": daily_scan_steps(""),
                }
        except ValueError:
            pass
    return {"current": current, "runs": runs[:8]}


def daily_briefing_cache_key(platform: str, sport_filter: str | None) -> str:
    platform_key = (
        "".join(ch.lower() if ch.isalnum() else "_" for ch in (platform or "PrizePicks")).strip("_") or "prizepicks"
    )
    sport_key = (
        "".join(ch.lower() if ch.isalnum() else "_" for ch in (sport_filter or "all_sports")).strip("_") or "all_sports"
    )
    return f"daily_briefing_cache:{platform_key}:{sport_key}"


def daily_briefing_cache_is_fresh(cached: dict, ttl_hours: int) -> bool:
    now = utc_now()
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    expires_at = str(cached.get("expires_at") or "").strip()
    if expires_at:
        try:
            expires = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
            if expires.tzinfo is None:
                expires = expires.replace(tzinfo=UTC)
            return expires > now
        except ValueError:
            return False

    created_at = str(cached.get("created_at") or "").strip()
    if not created_at:
        return False
    try:
        created = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        if created.tzinfo is None:
            created = created.replace(tzinfo=UTC)
    except ValueError:
        return False
    if created.date() != now.date():
        return False
    return now - created < timedelta(hours=ttl_hours)


def cached_daily_briefing_payload(
    platform: str,
    sport_filter: str | None,
    *,
    refresh: bool,
    cached_only: bool,
    cache_version: int,
    ttl_hours: int,
    get_setting: GetSetting,
    set_setting: SetSetting,
    safe_json_loads: Callable[[str], object],
    build_payload: Callable[[str, str | None], dict],
    refresh_runtime_state: Callable[[dict], dict],
    build_placeholder: Callable[[str, str | None, str], dict],
) -> dict:
    key = daily_briefing_cache_key(platform, sport_filter)
    if not refresh:
        raw_cached = safe_json_loads(get_setting(key, ""))
        cached = raw_cached if isinstance(raw_cached, dict) else {}
        payload = cached.get("payload") if cached.get("version") == cache_version else None
        if isinstance(payload, dict):
            fresh = daily_briefing_cache_is_fresh(cached, ttl_hours)
            payload = refresh_runtime_state(payload)
            return {
                **payload,
                "cache": {
                    "hit": True,
                    "key": key,
                    "created_at": cached.get("created_at", payload.get("as_of", "")),
                    "expires_at": cached.get("expires_at", ""),
                    "ttl_hours": ttl_hours,
                    "stale": not fresh,
                    "requires_refresh": not fresh,
                    "refreshed": False,
                },
            }
        if cached_only:
            return build_placeholder(platform, sport_filter, key)

    payload = build_payload(platform, sport_filter)
    created_at = iso_utc(utc_now())
    expires_at = iso_utc(utc_now() + timedelta(hours=ttl_hours))
    set_setting(
        key,
        json.dumps(
            {
                "created_at": created_at,
                "expires_at": expires_at,
                "version": cache_version,
                "payload": payload,
            }
        ),
    )
    return {
        **payload,
        "cache": {
            "hit": False,
            "key": key,
            "created_at": created_at,
            "expires_at": expires_at,
            "ttl_hours": ttl_hours,
            "stale": False,
            "requires_refresh": False,
            "refreshed": True,
        },
    }
