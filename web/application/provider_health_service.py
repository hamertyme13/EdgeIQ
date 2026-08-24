from __future__ import annotations

import json
import os
import re
from datetime import UTC, datetime

from data.providers import pandascore, sleeper
from data.providers.cache import cache_metrics
from repository.repositories.settings_repository import SettingsRepository
from utils.time import utc_now
from web.application.provider_contracts import enrich_provider_health


def build_data_health_payload(
    provider_weights: dict[str, float],
    platform_memory: dict[str, dict[str, int]],
    settlement_status_key: str,
    endpoint_timings: dict | None = None,
    operational_health: dict | None = None,
) -> dict:
    providers = [
        provider_health_row("PrizePicks", "props", configured=True, key_env="", settlement_status_key=settlement_status_key),
        provider_health_row("Underdog", "props", configured=True, key_env="", settlement_status_key=settlement_status_key),
        sleeper_health_row(),
        provider_health_row(
            "OpenAI",
            "AI recommendations/screenshots",
            configured=bool(os.getenv("OPENAI_API_KEY")),
            key_env="OPENAI_API_KEY",
            settlement_status_key=settlement_status_key,
        ),
        provider_health_row(
            "SportsDataIO",
            "optional NFL/NBA/NHL final-stat cross-check",
            configured=bool(os.getenv("SPORTSDATAIO_API_KEY")),
            key_env="SPORTSDATAIO_API_KEY",
            settlement_status_key=settlement_status_key,
        ),
        provider_health_row(
            "NewsAPI",
            "news context",
            configured=bool(os.getenv("NEWSAPI_KEY")),
            key_env="NEWSAPI_KEY",
            settlement_status_key=settlement_status_key,
        ),
        provider_health_row(
            "OpenWeather",
            "outdoor weather",
            configured=bool(os.getenv("OPENWEATHER_API_KEY")),
            key_env="OPENWEATHER_API_KEY",
            settlement_status_key=settlement_status_key,
        ),
        provider_health_row(
            "The Odds API",
            "multi-book prices and no-vig market consensus",
            configured=bool(os.getenv("ODDS_API_KEY")),
            key_env="ODDS_API_KEY",
            settlement_status_key=settlement_status_key,
        ),
        provider_health_row(
            "Ball Don't Lie",
            "player stats",
            configured=bool(os.getenv("BALLDONTLIE_API_KEY") or os.getenv("BALLDONTLIE_PROPS_URL")),
            key_env="BALLDONTLIE_API_KEY",
            settlement_status_key=settlement_status_key,
        ),
        provider_health_row(
            "ESPN public",
            "final stats/injuries",
            configured=True,
            key_env="",
            settlement_status_key=settlement_status_key,
        ),
        provider_health_row(
            "NBA Stats",
            "Summer League final stats",
            configured=True,
            key_env="",
            settlement_status_key=settlement_status_key,
        ),
        pandascore_health_row(settlement_status_key),
    ]
    providers = [enrich_provider_health(provider) for provider in providers]
    api_usage = dict(cache_metrics())
    memory_avoided = sum(
        metrics.get("memory_cache_hits", 0) + metrics.get("coalesced_hits", 0)
        for metrics in platform_memory.values()
    )
    api_usage["platform_memory"] = platform_memory
    api_usage["requests_avoided"] = int(api_usage.get("requests_avoided") or 0) + memory_avoided
    network_requests = int((api_usage.get("totals") or {}).get("network_requests") or 0)
    considered = int(api_usage["requests_avoided"]) + network_requests
    api_usage["avoidance_pct"] = (
        round(api_usage["requests_avoided"] / considered * 100.0, 1)
        if considered
        else 0.0
    )
    for provider in providers:
        provider["api_usage"] = provider_api_usage(provider["name"], api_usage)
    connected = sum(
        1
        for provider in providers
        if provider["status"] in {"connected", "available", "fresh"}
    )
    warnings = [
        provider
        for provider in providers
        if provider["status"] in {"missing_key", "not_configured", "stale", "degraded"}
    ]
    operational_health = operational_health or {}
    scheduler = operational_health.get("scheduler") or {}
    schedule = operational_health.get("schedule") or {}
    shadow = operational_health.get("shadow_evaluation") or {}
    settlement = operational_health.get("shadow_settlement") or {}
    research_memory = operational_health.get("research_memory") or {}
    plausibility_rejections = operational_health.get("plausibility_rejections") or []
    operational_warnings = []
    if scheduler.get("failures"):
        operational_warnings.append("One or more scheduled jobs failed during the latest maintenance run.")
    overdue_jobs = schedule.get("overdue_jobs") or []
    if overdue_jobs:
        labels = ", ".join(str(job.get("name") or job.get("key") or "scheduled job") for job in overdue_jobs[:3])
        operational_warnings.append(f"Scheduled maintenance is overdue: {labels}.")
    if int(shadow.get("settlement_failures") or 0) > 0:
        operational_warnings.append("Some shadow predictions could not be matched to verified final stats after repeated attempts.")
    if shadow.get("queued") and not shadow.get("settled") and settlement.get("ran_at"):
        operational_warnings.append("Shadow settlement is running, but no verified outcomes have settled yet.")
    return {
        "providers": providers,
        "provider_weights": provider_weights,
        "api_usage": api_usage,
        "endpoint_performance": endpoint_timings or {
            "requests": 0,
            "slow_requests": 0,
            "slow_threshold_ms": 1000,
            "routes": [],
        },
        "operations": {
            "scheduler": scheduler,
            "schedule": schedule,
            "shadow_settlement": settlement,
            "shadow_evaluation": shadow,
            "research_memory": research_memory,
            "plausibility_rejections": plausibility_rejections,
            "warnings": operational_warnings,
            "status": "degraded" if operational_warnings else "healthy",
        },
        "summary": {
            "connected": connected,
            "total": len(providers),
            "warnings": len(warnings) + len(operational_warnings),
            "last_daily_refresh": SettingsRepository.get("last_daily_refresh", ""),
        },
    }


def provider_api_usage(name: str, usage: dict) -> dict:
    host_fragments = {
        "PrizePicks": ("prizepicks.com",),
        "Underdog": ("underdogfantasy.com",),
        "Sleeper": ("sleeper.app",),
        "OpenAI": ("openai.com",),
        "SportsDataIO": ("sportsdata.io",),
        "NewsAPI": ("newsapi.org",),
        "OpenWeather": ("openweathermap.org",),
        "The Odds API": ("the-odds-api.com",),
        "Ball Don't Lie": ("balldontlie.io",),
        "ESPN public": ("espn.com",),
        "NBA Stats": ("nba.com",),
    }
    fragments = host_fragments.get(name, ())
    totals: dict[str, int] = {}
    for host, metrics in (usage.get("hosts") or {}).items():
        if not any(fragment in host for fragment in fragments):
            continue
        for metric, value in metrics.items():
            totals[metric] = totals.get(metric, 0) + int(value)
    avoided = totals.get("cache_hits", 0) + totals.get("coalesced_hits", 0) + totals.get("not_modified", 0)
    memory = (usage.get("platform_memory") or {}).get(name, {})
    avoided += int(memory.get("memory_cache_hits") or 0) + int(memory.get("coalesced_hits") or 0)
    return {
        **totals,
        **{f"memory_{key}": value for key, value in memory.items()},
        "requests_avoided": avoided,
        "used_this_session": bool(totals or memory),
    }


def provider_health_row(
    name: str,
    purpose: str,
    configured: bool,
    key_env: str,
    settlement_status_key: str,
) -> dict:
    has_key = bool(os.getenv(key_env, "").strip()) if key_env else configured
    runtime = _safe_json_loads(SettingsRepository.get(provider_status_key(name), ""))
    if name == "ESPN public" and not runtime:
        settlement = _safe_json_loads(SettingsRepository.get(settlement_status_key, ""))
        if settlement:
            runtime = {
                "last_attempt_at": settlement.get("ran_at", ""),
                "last_success_at": settlement.get("ran_at", "") if settlement.get("ok") else "",
                "last_error_at": settlement.get("ran_at", "") if not settlement.get("ok") else "",
                "last_error": "" if settlement.get("ok") else settlement.get("message", "refresh failed"),
                "row_count": settlement.get("imported", 0),
            }
    last_success = str(runtime.get("last_success_at") or "")
    age = age_minutes(last_success)
    if runtime.get("last_error") and (
        not last_success or str(runtime.get("last_error_at") or "") >= last_success
    ):
        status = "degraded"
    elif last_success and age is not None:
        status = "fresh" if age <= 30 else "stale"
    elif configured and has_key:
        status = "configured" if key_env else "available"
    elif configured and key_env and not has_key:
        status = "missing_key"
    else:
        status = "not_configured"
    return {
        "name": name,
        "purpose": purpose,
        "status": status,
        "configured": bool(configured),
        "key_env": key_env,
        "has_key": has_key,
        "last_success_at": last_success,
        "last_error": str(runtime.get("last_error") or ""),
        "age_minutes": age,
        "row_count": int(runtime.get("row_count") or 0),
        "message": provider_health_message(name, status, key_env, runtime),
    }


def provider_health_message(
    name: str,
    status: str,
    key_env: str,
    runtime: dict | None = None,
) -> str:
    runtime = runtime or {}
    if status == "fresh":
        return f"{name} returned {int(runtime.get('row_count') or 0)} usable rows recently."
    if status == "stale":
        return f"{name} last succeeded at {runtime.get('last_success_at')}; refresh before relying on it."
    if status == "degraded":
        return f"{name} most recent refresh failed: {runtime.get('last_error') or 'provider unavailable'}."
    if status in {"connected", "available"}:
        return f"{name} is available to EdgeIQ."
    if status == "configured":
        return f"{name} is configured but has not completed a recent verified refresh."
    if status == "missing_key":
        return f"Set {key_env} to enable {name}."
    return f"{name} is not configured yet."


def age_minutes(value: object) -> int | None:
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
    current = utc_now()
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    return max(0, int((current.astimezone(UTC) - parsed.astimezone(UTC)).total_seconds() / 60))


def provider_status_key(name: object) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", str(name or "").strip().lower()).strip("_") or "unknown"
    return f"provider_fetch_status:{slug}"


def pandascore_health_row(settlement_status_key: str) -> dict:
    row = provider_health_row(
        "PandaScore",
        "verified CS2, League of Legends, Dota 2, and Valorant final player stats",
        configured=pandascore.configured(),
        key_env="PANDASCORE_API_KEY",
        settlement_status_key=settlement_status_key,
    )
    if pandascore.key_configured() and not pandascore.configured():
        row.update({
            "status": "degraded",
            "configured": False,
            "has_key": True,
            "message": (
                "The PandaScore key is valid, but Historical player-stat access is not confirmed. "
                "Upgrade the plan, then set PANDASCORE_HISTORICAL_STATS_ENABLED=true."
            ),
        })
    return row


def sleeper_health_row() -> dict:
    status = sleeper.public_api_status()
    player_cache = status["player_cache"]
    cache_label = "fresh" if player_cache["fresh"] else "not warmed"
    if player_cache["cached"] and not player_cache["fresh"]:
        cache_label = "stale"
    return {
        "name": "Sleeper",
        "purpose": "public NFL player metadata/trends; optional prop-feed import",
        "status": "available",
        "configured": True,
        "key_env": "",
        "has_key": False,
        "auth_required": False,
        "read_only": True,
        "props_configured": status["props_configured"],
        "player_cache": player_cache,
        "message": (
            "No API key needed. Public read-only trends are available; "
            f"player cache is {cache_label}. "
            f"{'Prop feed configured.' if status['props_configured'] else 'Configure a Sleeper prop feed only if you want Sleeper lines.'}"
        ),
    }


def _safe_json_loads(value: str) -> dict:
    try:
        return json.loads(value) if value else {}
    except (TypeError, ValueError):
        return {}
