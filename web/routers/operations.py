from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

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
    start_daily_refresh: Callable[[], dict]
    start_feature_refresh: Callable[[], dict]
    feature_status: Callable[[], dict]
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


_deps_store: list[OperationsDependencies] = []


def configure_operations_router(dependencies: OperationsDependencies) -> None:
    if _deps_store:
        _deps_store[0] = dependencies
    else:
        _deps_store.append(dependencies)


def get_deps() -> OperationsDependencies:
    if not _deps_store:
        raise HTTPException(status_code=503, detail="App settings are still starting. Please try again.")
    return _deps_store[0]


DepsOps = Annotated[OperationsDependencies, Depends(get_deps)]


@router.post("/api/sync/run")
def run_sync(allow_estimates: bool = False, deps: DepsOps = None) -> dict:  # type: ignore[assignment]
    _deps = deps if isinstance(deps, OperationsDependencies) else get_deps()
    return _deps.sync(allow_estimates)


@router.get("/api/settings/dnp")
def dnp_setting(deps: DepsOps = None) -> dict:  # type: ignore[assignment]
    _deps = deps if isinstance(deps, OperationsDependencies) else get_deps()
    return _deps.dnp_setting()


@router.post("/api/settings/dnp")
def update_dnp_setting(payload: DnpSettingPayload, deps: DepsOps = None) -> dict:  # type: ignore[assignment]
    _deps = deps if isinstance(deps, OperationsDependencies) else get_deps()
    return _deps.update_dnp(payload)


@router.get("/api/settings/preferences")
def user_preferences(deps: DepsOps = None) -> dict:  # type: ignore[assignment]
    _deps = deps if isinstance(deps, OperationsDependencies) else get_deps()
    return _deps.preferences()


@router.post("/api/settings/preferences")
def update_user_preferences(payload: UserPreferencePayload, deps: DepsOps = None) -> dict:  # type: ignore[assignment]
    _deps = deps if isinstance(deps, OperationsDependencies) else get_deps()
    return _deps.update_preferences(payload)


@router.get("/api/settings/provider-weights")
def provider_weights(deps: DepsOps = None) -> dict:  # type: ignore[assignment]
    _deps = deps if isinstance(deps, OperationsDependencies) else get_deps()
    return _deps.provider_weights()


@router.post("/api/settings/provider-weights")
def update_provider_weights(payload: ProviderWeightsPayload, deps: DepsOps = None) -> dict:  # type: ignore[assignment]
    _deps = deps if isinstance(deps, OperationsDependencies) else get_deps()
    return _deps.update_provider_weights(payload)


@router.get("/api/automation/refresh-schedule")
def refresh_schedule(deps: DepsOps = None) -> dict:  # type: ignore[assignment]
    _deps = deps if isinstance(deps, OperationsDependencies) else get_deps()
    return _deps.refresh_schedule()


@router.post("/api/automation/refresh-schedule")
def update_refresh_schedule(payload: RefreshSchedulePayload, deps: DepsOps = None) -> dict:  # type: ignore[assignment]
    _deps = deps if isinstance(deps, OperationsDependencies) else get_deps()
    return _deps.update_refresh_schedule(payload)


@router.post("/api/automation/run-daily-refresh")
def run_daily_refresh(deps: DepsOps = None) -> dict:  # type: ignore[assignment]
    _deps = deps if isinstance(deps, OperationsDependencies) else get_deps()
    return _deps.run_daily_refresh()


@router.post("/api/automation/start-daily-refresh", status_code=202)
def start_daily_refresh(deps: DepsOps = None) -> dict:  # type: ignore[assignment]
    _deps = deps if isinstance(deps, OperationsDependencies) else get_deps()
    return _deps.start_daily_refresh()


@router.post("/api/player-features/jobs", status_code=202)
def start_player_feature_refresh(deps: DepsOps = None) -> dict:  # type: ignore[assignment]
    _deps = deps if isinstance(deps, OperationsDependencies) else get_deps()
    return _deps.start_feature_refresh()


@router.get("/api/player-features/status")
def player_feature_status(deps: DepsOps = None) -> dict:  # type: ignore[assignment]
    _deps = deps if isinstance(deps, OperationsDependencies) else get_deps()
    return _deps.feature_status()


@router.get("/api/settings/alert-delivery")
def alert_delivery_settings(deps: DepsOps = None) -> dict:  # type: ignore[assignment]
    _deps = deps if isinstance(deps, OperationsDependencies) else get_deps()
    return _deps.alert_delivery()


@router.post("/api/settings/alert-delivery")
def update_alert_delivery_settings(payload: AlertDeliveryPayload, deps: DepsOps = None) -> dict:  # type: ignore[assignment]
    _deps = deps if isinstance(deps, OperationsDependencies) else get_deps()
    return _deps.update_alert_delivery(payload)


@router.post("/api/alerts/test-delivery")
def test_alert_delivery(payload: AlertDeliveryTestPayload, deps: DepsOps = None) -> dict:  # type: ignore[assignment]
    _deps = deps if isinstance(deps, OperationsDependencies) else get_deps()
    return _deps.test_alert_delivery(payload)


@router.get("/api/deploy/readiness")
def deploy_readiness(deps: DepsOps = None) -> dict:  # type: ignore[assignment]
    _deps = deps if isinstance(deps, OperationsDependencies) else get_deps()
    return _deps.deploy_readiness()


@router.get("/api/runtime/status")
def runtime_status(deps: DepsOps = None) -> dict:  # type: ignore[assignment]
    _deps = deps if isinstance(deps, OperationsDependencies) else get_deps()
    return _deps.runtime_status()


@router.get("/api/notifications")
def notifications(deps: DepsOps = None) -> dict:  # type: ignore[assignment]
    _deps = deps if isinstance(deps, OperationsDependencies) else get_deps()
    return _deps.notifications()


@router.get("/api/watchlist")
def watchlist(deps: DepsOps = None) -> dict:  # type: ignore[assignment]
    _deps = deps if isinstance(deps, OperationsDependencies) else get_deps()
    return _deps.watchlist()


@router.post("/api/watchlist")
def save_watchlist_item(payload: WatchlistItemPayload, deps: DepsOps = None) -> dict:  # type: ignore[assignment]
    _deps = deps if isinstance(deps, OperationsDependencies) else get_deps()
    return _deps.save_watchlist(payload)


@router.delete("/api/watchlist/{item_id}")
def delete_watchlist_item(item_id: str, deps: DepsOps = None) -> dict:  # type: ignore[assignment]
    _deps = deps if isinstance(deps, OperationsDependencies) else get_deps()
    return _deps.delete_watchlist(item_id)


@router.get("/api/watchlist/alerts")
def watchlist_alerts(deps: DepsOps = None) -> dict:  # type: ignore[assignment]
    _deps = deps if isinstance(deps, OperationsDependencies) else get_deps()
    return _deps.watchlist_alerts()


@router.get("/api/integrations/sportsbooks")
def sportsbook_integrations(deps: DepsOps = None) -> dict:  # type: ignore[assignment]
    _deps = deps if isinstance(deps, OperationsDependencies) else get_deps()
    return _deps.sportsbook_integrations()
