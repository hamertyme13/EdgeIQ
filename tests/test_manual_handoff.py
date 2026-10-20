from web.application.manual_handoff import review_stake

STRATEGY = {"unit_size": 10, "max_wager_pct": 5, "max_open_exposure_pct": 15}


def test_prizepicks_handoff_requires_manual_balance():
    result = review_stake(
        wager=10, bankroll=200, open_exposure=0, strategy=STRATEGY,
        provider_balance=None, require_provider_balance=True,
    )
    assert result["blocks"]
    assert "cannot read it automatically" in result["blocks"][0]
    assert result["maximum"] == 0


def test_handoff_caps_wager_by_bankroll_exposure_and_provider_balance():
    result = review_stake(
        wager=10, bankroll=200, open_exposure=25, strategy=STRATEGY,
        provider_balance=7, require_provider_balance=True,
    )
    assert result["maximum"] == 5
    assert result["suggested"] == 5
    assert any("exceeds" in reason for reason in result["blocks"])


def test_handoff_allows_wager_within_all_limits():
    result = review_stake(
        wager=5, bankroll=200, open_exposure=0, strategy=STRATEGY,
        provider_balance=30, require_provider_balance=True,
    )
    assert result["maximum"] == 10
    assert result["suggested"] == 10
    assert result["blocks"] == []


def test_other_platform_does_not_require_prizepicks_balance():
    result = review_stake(
        wager=5, bankroll=200, open_exposure=0, strategy=STRATEGY,
        provider_balance=None, require_provider_balance=False,
    )
    assert result["blocks"] == []


def test_prizepicks_handoff_readiness_requires_manual_balance(monkeypatch):
    import web.app as web_app
    from web.schemas import EntryPayload

    monkeypatch.setattr(web_app, "validate_entry_evidence_payload", lambda payload: {
        "invalidations": [], "warnings": [],
    })
    monkeypatch.setattr(web_app, "_entry_from_payload", lambda payload: object())
    monkeypatch.setattr(web_app, "_entry_analysis", lambda entry, payload: {
        "risk_guardrails": [], "release_verdict": {"paid_allowed": True},
    })
    monkeypatch.setattr(web_app, "_fetch_props", lambda platform, sport: [])
    monkeypatch.setattr(web_app, "_platform_value_check", lambda *args, **kwargs: {
        "recommended_platform": "PrizePicks", "payout_verified": True,
    })
    monkeypatch.setattr(web_app, "_verify_handoff_live_offers", lambda *args, **kwargs: {
        "legs": [{"freshness_status": "fresh"}], "all_current": True,
    })
    monkeypatch.setattr(web_app, "_handoff_copy_text", lambda *args: "Manual slip")
    monkeypatch.setattr(web_app, "_cached_dashboard_stats", lambda: {"bankroll": 200})
    monkeypatch.setattr(web_app, "_open_real_money_exposure", lambda: 0)
    monkeypatch.setattr(web_app, "_bankroll_strategy", lambda: STRATEGY)
    payload = EntryPayload.model_validate({
        "platform": "PrizePicks", "entry_mode": "real", "wager": 5,
        "props": [
            {"player": "A", "sport": "WNBA", "stat": "Points", "line": 12.5},
            {"player": "B", "sport": "WNBA", "stat": "Points", "line": 14.5},
        ],
    })

    blocked = web_app._entry_handoff_payload(payload)
    assert not blocked["ready_for_handoff"]
    assert blocked["stake_review"]["maximum"] == 0
    payload.provider_available_balance = 20
    ready = web_app._entry_handoff_payload(payload)
    assert ready["ready_for_handoff"]
    assert ready["stake_review"]["suggested"] == 10
