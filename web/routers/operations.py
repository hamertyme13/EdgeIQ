from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from fastapi import APIRouter, BackgroundTasks, HTTPException

from web.schemas import (
    AlertDeliveryPayload,
    AlertDeliveryTestPayload,
    DnpSettingPayload,
    ProviderWeightsPayload,
    RefreshSchedulePayload,
    UserPreferencePayload,
    WatchlistItemPayload,
)

router = APIRouter(tags=["operations"])


@dataclass(frozen=True)
class OperationsDependencies:
    sync: Callable[[bool], dict]
    dnp_setting: Callable[[], dict]
    update_dnp: Callable[[DnpSettingPayload], dict]
    preferences: Callable[[], dict]
    update_preferences: Callable[[UserPreferencePayload], dict]
    provider_weights: Callable[[], dict]
    update_provider_weights: Callable[[ProviderWeightsPayload], dict]
    refresh_schedule: Callable[[], dict]
    update_refresh_schedule: Callable[[RefreshSchedulePayload], dict]
    run_daily_refresh: Callable[[], dict]
    alert_delivery: Callable[[], dict]
    update_alert_delivery: Callable[[AlertDeliveryPayload], dict]
    test_alert_delivery: Callable[[AlertDeliveryTestPayload], dict]
    deploy_readiness: Callable[[], dict]
    runtime_status: Callable[[], dict]
    notifications: Callable[[], dict]
    watchlist: Callable[[], dict]
    save_watchlist: Callable[[WatchlistItemPayload], dict]
    delete_watchlist: Callable[[str], dict]
    watchlist_alerts: Callable[[], dict]
    sportsbook_integrations: Callable[[], dict]


_dependencies: OperationsDependencies | None = None


def configure_operations_router(dependencies: OperationsDependencies) -> None:
    global _dependencies
    _dependencies = dependencies


def _deps() -> OperationsDependencies:
    if _dependencies is None:
        raise HTTPException(status_code=503, detail="App settings are still starting. Please try again.")
    return _dependencies


@router.post("/api/sync/run")
def run_sync(allow_estimates: bool = False) -> dict:
    return _deps().sync(allow_estimates)


@router.get("/api/settings/dnp")
def dnp_setting() -> dict:
    return _deps().dnp_setting()


@router.post("/api/settings/dnp")
def update_dnp_setting(payload: DnpSettingPayload) -> dict:
    return _deps().update_dnp(payload)


@router.get("/api/settings/preferences")
def user_preferences() -> dict:
    return _deps().preferences()


@router.post("/api/settings/preferences")
def update_user_preferences(payload: UserPreferencePayload) -> dict:
    return _deps().update_preferences(payload)


@router.get("/api/settings/provider-weights")
def provider_weights() -> dict:
    return _deps().provider_weights()


@router.post("/api/settings/provider-weights")
def update_provider_weights(payload: ProviderWeightsPayload) -> dict:
    return _deps().update_provider_weights(payload)


@router.get("/api/automation/refresh-schedule")
def refresh_schedule() -> dict:
    return _deps().refresh_schedule()


@router.post("/api/automation/refresh-schedule")
def update_refresh_schedule(payload: RefreshSchedulePayload) -> dict:
    return _deps().update_refresh_schedule(payload)


@router.post("/api/automation/run-daily-refresh")
def run_daily_refresh() -> dict:
    return _deps().run_daily_refresh()


@router.post("/api/automation/start-daily-refresh", status_code=202)
def start_daily_refresh(background_tasks: BackgroundTasks) -> dict:
    background_tasks.add_task(_deps().run_daily_refresh)
    return {
        "accepted": True,
        "message": "Provider refresh started. You can keep using EdgeIQ while it finishes.",
    }


@router.get("/api/settings/alert-delivery")
def alert_delivery_settings() -> dict:
    return _deps().alert_delivery()


@router.post("/api/settings/alert-delivery")
def update_alert_delivery_settings(payload: AlertDeliveryPayload) -> dict:
    return _deps().update_alert_delivery(payload)


@router.post("/api/alerts/test-delivery")
def test_alert_delivery(payload: AlertDeliveryTestPayload) -> dict:
    return _deps().test_alert_delivery(payload)


@router.get("/api/deploy/readiness")
def deploy_readiness() -> dict:
    return _deps().deploy_readiness()


@router.get("/api/runtime/status")
def runtime_status() -> dict:
    return _deps().runtime_status()


@router.get("/api/notifications")
def notifications() -> dict:
    return _deps().notifications()


@router.get("/api/watchlist")
def watchlist() -> dict:
    return _deps().watchlist()


@router.post("/api/watchlist")
def save_watchlist_item(payload: WatchlistItemPayload) -> dict:
    return _deps().save_watchlist(payload)


@router.delete("/api/watchlist/{item_id}")
def delete_watchlist_item(item_id: str) -> dict:
    return _deps().delete_watchlist(item_id)


@router.get("/api/watchlist/alerts")
def watchlist_alerts() -> dict:
    return _deps().watchlist_alerts()


@router.get("/api/integrations/sportsbooks")
def sportsbook_integrations() -> dict:
    return _deps().sportsbook_integrations()
