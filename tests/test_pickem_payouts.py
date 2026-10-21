import pytest

from analytics.pickem_payouts import payout_analysis, payout_schedule, settlement_return_multiplier


def test_draftkings_pick6_uses_user_entered_multiplier_without_claiming_official_schedule() -> None:
    result = payout_analysis([0.6, 0.6, 0.6], "DraftKings Pick6", displayed_multiplier=5.0)

    assert result["platform"] == "DraftKings Pick6"
    assert result["source"] == "user_entered_multiplier"
    assert result["payouts"] == {"3": 5.0}


def test_prizepicks_flex_expected_value_includes_partial_payouts():
    result = payout_analysis([0.6, 0.6, 0.6], "PrizePicks", "flex")

    assert result["payouts"] == {"3": 3.0, "2": 1.0}
    assert result["expected_return"] == 1.08
    assert result["expected_value"] == 8.0


def test_prizepicks_two_pick_flex_uses_published_partial_payout():
    result = payout_analysis([0.6, 0.6], "PrizePicks", "flex")

    assert result["payouts"] == {"2": 2.0, "1": 0.5}
    assert result["expected_value"] == -4.0


def test_user_entered_payout_is_not_labeled_provider_snapshot():
    result = payout_analysis(
        [0.6, 0.6], "PrizePicks", "flex",
        exact_schedule={"2": 2.0, "1": 0.5},
        exact_schedule_source="user_entered_payout",
    )

    assert result["source"] == "user_entered_payout"
    assert result["requires_app_confirmation"] is True


def test_underdog_standard_uses_current_base_multiplier():
    assert payout_schedule("Underdog", "standard", 3) == {3: 6.5}


def test_displayed_multiplier_scales_adjusted_entry():
    result = payout_analysis([0.7, 0.7, 0.7], "PrizePicks", "standard", displayed_multiplier=9.0)

    assert result["displayed_multiplier"] == 9.0
    assert result["expected_return"] == 3.087
    assert result["break_even_probability"] == 11.11


def test_flex_settlement_uses_partial_win_multiplier():
    multiplier = settlement_return_multiplier(
        "Underdog",
        "flex",
        [{"result": "Win"}, {"result": "Win"}, {"result": "Loss"}],
    )

    assert multiplier == 1.09


def test_flex_settlement_prefers_saved_exact_payout_over_generic_schedule():
    from repository.repositories.entry_repository import EntryRepository

    result, profit = EntryRepository._settlement_profit(
        "Loss", 10, 5, 3, platform="PrizePicks", payout_type="flex",
        leg_results=[{"result": "Win"}, {"result": "Win"}, {"result": "Loss"}],
        exact_schedule={"3": 5.0, "2": 1.5},
    )
    assert (result, profit) == ("Win", 5.0)


def test_flex_settlement_does_not_apply_original_exact_table_after_void():
    multiplier = settlement_return_multiplier(
        "PrizePicks", "flex",
        [{"result": "Win"}, {"result": "Win"}, {"result": "DNP"}],
        exact_schedule={"3": 5.0, "2": 1.5},
    )
    assert multiplier == 2.0


def test_standard_settlement_rejects_unresolved_leg():
    from repository.repositories.entry_repository import EntryRepository

    with pytest.raises(ValueError, match="verified final result"):
        EntryRepository._settlement_profit(
            "Loss", 10, 3, 2,
            leg_results=[{"result": "Loss"}, {"result": "Unknown"}],
        )


def test_saved_flex_entry_settles_with_its_exact_payout_table(db_session, monkeypatch):
    import json

    from sqlalchemy.orm import sessionmaker

    from repository.models.entry_model import EntryModel
    from repository.models.entry_prop_model import EntryPropModel
    from repository.repositories import entry_repository
    from repository.repositories.entry_repository import EntryRepository

    monkeypatch.setattr(entry_repository, "SessionLocal", sessionmaker(bind=db_session.connection()))
    monkeypatch.setattr(EntryRepository, "_ensure_schema", lambda: None)
    monkeypatch.setattr(EntryRepository, "_sync_entry_to_bet_history", lambda entry: None)
    entry = EntryModel(
        platform="PrizePicks", average_confidence=60.0, average_edge=1.5,
        wager=10.0, multiplier=5.0, payout_type="flex", status="Pending",
        entry_mode="real", payout_table_snapshot=json.dumps({
            "source": "user_entered_payout", "payouts": {"3": 5.0, "2": 1.5},
        }),
    )
    db_session.add(entry)
    db_session.flush()
    for index in range(3):
        db_session.add(EntryPropModel(
            entry_id=entry.id, player_name=f"Flex Test {index}", sport="WNBA",
            stat="Points", line=15.5, direction="Over", platform="PrizePicks",
        ))
    db_session.flush()

    settled = EntryRepository.settle(
        entry.id, "Loss",
        leg_results=[
            {"result": "Win", "actual": 20.0, "source": "espn", "final_status": "played"},
            {"result": "Win", "actual": 20.0, "source": "espn", "final_status": "played"},
            {"result": "Loss", "actual": 10.0, "source": "espn", "final_status": "played"},
        ],
    )
    assert settled["result"] == "Win"
    assert settled["profit"] == 5.0


def test_all_winning_pick6_flex_uses_recorded_multiplier():
    assert settlement_return_multiplier("DraftKings Pick6", "flex", [{"result": "Win"}] * 3, 5.0) == 5.0


def test_unknown_flex_payout_is_not_silently_a_loss():
    with pytest.raises(ValueError, match="not verified"):
        settlement_return_multiplier("DraftKings Pick6", "flex", [{"result": "Win"}] * 2 + [{"result": "Loss"}], 5.0)


def test_unresolved_leg_cannot_be_settled_as_loss():
    with pytest.raises(ValueError, match="final result"):
        settlement_return_multiplier("PrizePicks", "flex", [{"result": "Win"}] * 2 + [{"result": "Unknown"}])


def test_complete_winning_leg_set_overrides_contradictory_entry_loss():
    from repository.repositories.entry_repository import EntryRepository
    result, profit = EntryRepository._settlement_profit("Loss", 10, 5, 3, leg_results=[{"result": "Win"}] * 3)
    assert result == "Win"
    assert profit == 40


def test_zero_wager_flex_uses_return_multiplier_for_result(monkeypatch) -> None:
    from repository.repositories import entry_repository

    monkeypatch.setattr(entry_repository, "settlement_return_multiplier", lambda *args, **kwargs: 0.0)
    result, profit = entry_repository.EntryRepository._settlement_profit(
        "Loss", 0, 8.1, 6, platform="DraftKings Pick6", payout_type="flex",
        leg_results=[{"result": "Win"}] * 2 + [{"result": "Loss"}] * 4,
    )
    assert (result, profit) == ("Loss", 0.0)


def test_standard_three_leg_card_with_exact_tie_reduces_to_winning_two_leg_card() -> None:
    from repository.repositories.entry_repository import EntryRepository

    result, profit = EntryRepository._settlement_profit(
        "Push", 0, 1, 3, platform="PrizePicks", payout_type="standard",
        leg_results=[{"result": "Win"}, {"result": "Win"}, {"result": "Push"}],
    )
    assert (result, profit) == ("Win", 0.0)
    result_with_refund_setting, _ = EntryRepository._settlement_profit(
        "Push", 0, 1, 3, dnp_mode="refund", platform="PrizePicks",
        leg_results=[{"result": "Win"}, {"result": "Win"}, {"result": "Push"}],
    )
    assert result_with_refund_setting == "Win"


def test_exact_offer_and_correlation_are_used_for_ev() -> None:
    independent = payout_analysis([0.6, 0.6], "PrizePicks", exact_schedule={"2": 3.0})
    correlated = payout_analysis(
        [0.6, 0.6],
        "PrizePicks",
        exact_schedule={"2": 3.0},
        correlation_matrix=[[1.0, 0.25], [0.25, 1.0]],
    )

    assert correlated["source"] == "exact_offer_snapshot"
    assert correlated["requires_app_confirmation"] is False
    assert correlated["correlation_adjusted"] is True
    assert correlated["all_hit_probability"] != independent["all_hit_probability"]
