import json
from datetime import UTC, datetime, timedelta

import web.app as web_app


def _entry(*, hours_ago=72, payout_type="standard", missing_time=False):
    start = datetime.now(UTC) - timedelta(hours=hours_ago)
    game_time = "" if missing_time else start.isoformat()
    return {
        "id": 99,
        "status": "Pending",
        "entry_mode": "real",
        "payout_type": payout_type,
        "placed_at": start,
        "props": [
            {"sport": "NFL", "game_time": game_time},
            {"sport": "NFL", "game_time": game_time},
            {"sport": "NFL", "game_time": game_time},
        ],
    }


def _legs(entry):
    return [
        {**entry["props"][0], "result": "Loss", "final_status": "played", "source": "espn"},
        {**entry["props"][1], "result": "Win", "final_status": "played", "source": "espn"},
        {**entry["props"][2], "result": "Unknown", "final_status": "unknown", "source": "unmatched"},
    ]


def test_past_due_standard_card_closes_only_after_entire_slate_window():
    mature = _entry()
    assert web_app._past_due_verified_standard_loss(mature, _legs(mature)) is True
    active = _entry(hours_ago=2)
    assert web_app._past_due_verified_standard_loss(active, _legs(active)) is False
    missing_time = _entry(hours_ago=24, missing_time=True)
    assert web_app._past_due_verified_standard_loss(missing_time, _legs(missing_time)) is False
    older_missing_time = _entry(hours_ago=72, missing_time=True)
    assert web_app._past_due_verified_standard_loss(older_missing_time, _legs(older_missing_time)) is False
    oldest_missing_time = _entry(hours_ago=8 * 24, missing_time=True)
    assert web_app._past_due_verified_standard_loss(oldest_missing_time, _legs(oldest_missing_time)) is True
    verified_missing_time = _entry(hours_ago=24)
    verified_missing_time["props"][0]["game_time"] = ""
    assert web_app._past_due_verified_standard_loss(verified_missing_time, _legs(verified_missing_time)) is True


def test_partial_loss_never_shortcuts_flex_or_unverified_outcomes():
    flex = _entry(payout_type="flex")
    assert web_app._past_due_verified_standard_loss(flex, _legs(flex)) is False
    standard = _entry()
    assert web_app._past_due_verified_standard_loss(standard, _legs(standard), dnp_mode="refund") is False
    estimated = _legs(standard)
    estimated[0]["source"] = "projection_estimate"
    assert web_app._past_due_verified_standard_loss(standard, estimated) is False
    dnp = _legs(standard)
    dnp[2]["result"] = "DNP"
    assert web_app._past_due_verified_standard_loss(standard, dnp) is False


def test_evaluator_keeps_missing_leg_unknown_on_past_due_loss(monkeypatch):
    entry = _entry()
    for index, prop in enumerate(entry["props"]):
        prop.update(player=f"Player {index}", stat="Receptions", line=5.5,
                    direction="Over", game="DAL@PHI")
    finals = {
        "Player 0": {"actual": 4, "status": "played", "source": "espn"},
        "Player 1": {"actual": 8, "status": "played", "source": "espn"},
        "Player 2": None,
    }
    monkeypatch.setattr(web_app, "_confirmed_final_stat_for_entry",
                        lambda prop, _entry: finals[prop["player"]])
    monkeypatch.setattr(web_app, "_record_settlement_audit", lambda *args: None)

    evaluation = web_app._evaluate_entry_result(entry, allow_estimates=False)

    assert evaluation["settled"] is True
    assert evaluation["result"] == "Loss"
    assert evaluation["partial_verified_loss"] is True
    assert [leg["result"] for leg in evaluation["legs"]] == ["Loss", "Win", "Unknown"]


def test_partial_verified_loss_stores_only_real_legs_and_audit_basis(monkeypatch):
    entry = _entry()
    legs = _legs(entry)
    calls = {}
    monkeypatch.setattr(web_app, "_evaluate_entry_result", lambda *_: {
        "settled": True, "result": "Loss", "source": "actual_provider",
        "partial_verified_loss": True, "message": "Verified past-due loss",
        "legs": legs, "dnp_legs": 0,
    })
    monkeypatch.setattr(web_app.EntryRepository, "store_partial_leg_results",
                        lambda entry_id, results: calls.update(stored=(entry_id, results)))
    monkeypatch.setattr(web_app.EntryRepository, "settle",
                        lambda entry_id, result, **kwargs: calls.update(settled=(entry_id, result, kwargs)))
    monkeypatch.setattr(web_app.ResearchEvidenceRepository, "record_outcome", lambda *_: None)

    result = web_app._check_entry_result(entry, allow_estimates=False)

    assert result["settled"] is True
    assert calls["stored"] == (99, legs)
    assert calls["settled"][2]["settlement_basis"] == "verified_standard_loss"
    assert "leg_results" not in calls["settled"][2]


def test_reopen_does_not_undo_verified_past_due_loss(monkeypatch):
    entry = _entry()
    entry.update(status="Settled", result="Loss", audit_snapshot=json.dumps({
        "settlement_basis": "verified_standard_loss",
    }))
    called = []
    monkeypatch.setattr(web_app.EntryRepository, "all", lambda: [entry])
    monkeypatch.setattr(web_app.EntryRepository, "reopen_for_settlement",
                        lambda *args: called.append(args))
    assert web_app._reopen_recent_partial_settlements() == []
    assert called == []
