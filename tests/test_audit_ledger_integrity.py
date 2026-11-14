from datetime import UTC, datetime, timedelta

from scripts.audit_ledger_integrity import entry_flags


def test_standard_card_with_all_winning_legs_cannot_be_a_loss():
    entry = {"status": "Settled", "result": "Loss", "payout_type": "standard"}
    legs = [{"final_result": "Win"}, {"final_result": "Win"}]
    assert entry_flags(entry, legs, now=datetime.now(UTC)) == ["all_winning_legs_but_card_not_win"]


def test_flex_win_with_losing_leg_is_not_flagged_as_a_standard_contradiction():
    entry = {"status": "Settled", "result": "Win", "payout_type": "flex"}
    legs = [{"final_result": "Win"}, {"final_result": "Loss"}]
    assert entry_flags(entry, legs, now=datetime.now(UTC)) == []


def test_standard_loss_remains_decided_when_another_leg_is_unknown():
    entry = {"status": "Settled", "result": "Loss", "payout_type": "standard"}
    legs = [{"final_result": "Loss"}, {"final_result": "Unknown"}]
    assert entry_flags(entry, legs, now=datetime.now(UTC)) == []


def test_pending_with_verified_legs_and_old_placement_gets_both_review_flags():
    entry = {"status": "Pending", "result": "", "payout_type": "standard",
             "placed_at": datetime.now(UTC) - timedelta(days=3)}
    legs = [{"final_result": "Win"}, {"final_result": "Push"}]
    assert entry_flags(entry, legs, now=datetime.now(UTC)) == [
        "pending_with_all_leg_results", "pending_more_than_two_days_since_placement",
    ]
