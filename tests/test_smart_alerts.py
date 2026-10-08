from datetime import UTC, datetime, timedelta

from web.application.smart_alerts import briefing_smart_alerts


def test_smart_alerts_are_opt_in_and_deduplicated():
    now = datetime.now(UTC)
    changes = {
        "available": True,
        "current_at": now.isoformat(),
        "events": [
            {"kind": "upgrades", "label": "Player · Points", "detail": "Grade improved"},
            {"kind": "upgrades", "label": "Player · Points", "detail": "Grade improved"},
            {"kind": "line_changes", "label": "Player · Points", "detail": "Line: 19.5 to 20"},
            {"kind": "line_changes", "label": "Other · Points", "detail": "Line: 19.5 to 21"},
        ],
    }
    assert briefing_smart_alerts(changes, {}, now=now) == []
    settings = {"smart_alerts_enabled": True, "smart_alert_types": ["upgrades", "line_changes"], "smart_alert_line_move": 1}
    alerts = briefing_smart_alerts(changes, settings, now=now)
    assert len(alerts) == 2
    assert {alert["title"] for alert in alerts} == {"Player · Points: upgrades", "Other · Points: line changes"}
    assert briefing_smart_alerts(changes, settings, now=now + timedelta(minutes=61)) == []


def test_smart_alerts_require_saved_comparison():
    settings = {"smart_alerts_enabled": True, "smart_alert_types": ["invalidated"]}
    assert briefing_smart_alerts({"available": False, "events": [{"kind": "invalidated"}]}, settings) == []
