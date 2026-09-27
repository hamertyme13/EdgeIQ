from datetime import UTC, datetime

from web.application import provider_health_service
from web.application.provider_contracts import provider_contract


def test_age_minutes_treats_naive_utc_now_as_utc(monkeypatch):
    monkeypatch.setattr(
        provider_health_service,
        "utc_now",
        lambda: datetime(2026, 8, 9, 6, 10),
    )

    assert provider_health_service.age_minutes("2026-08-09T06:04:00+00:00") == 6


def test_statshawk_health_explains_missing_key_and_settlement_scope(monkeypatch):
    monkeypatch.delenv("STATSHAWK_API_KEY", raising=False)
    monkeypatch.setattr(provider_health_service.SettingsRepository, "get", lambda *_args: "")
    row = provider_health_service.provider_health_row(
        "StatsHawk", "team-sport final box scores", False, "STATSHAWK_API_KEY", "settlement_status"
    )
    assert row["status"] == "not_configured"
    assert not row["verified_connection"]
    assert provider_contract("StatsHawk")["settlement_suitability"].startswith("Settlement")
    assert {"NBA", "WNBA", "NCAAF", "MLB", "NHL", "MLS"}.issubset(
        provider_contract("StatsHawk")["supported_sports"]
    )


def test_statshawk_api_usage_is_attributed_to_provider():
    usage = {"hosts": {"api.statshawk.ai": {"network_requests": 2, "cache_hits": 3}}}
    row = provider_health_service.provider_api_usage("StatsHawk", usage)
    assert row["network_requests"] == 2
    assert row["requests_avoided"] == 3
