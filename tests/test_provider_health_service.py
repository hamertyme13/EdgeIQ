from datetime import UTC, datetime

from web.application import provider_health_service


def test_age_minutes_treats_naive_utc_now_as_utc(monkeypatch):
    monkeypatch.setattr(
        provider_health_service,
        "utc_now",
        lambda: datetime(2026, 8, 9, 6, 10),
    )

    assert provider_health_service.age_minutes("2026-08-09T06:04:00+00:00") == 6
