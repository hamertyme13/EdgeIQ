from analytics.model_registry import OPPORTUNITY_CHALLENGER_VERSION, model_registry
from analytics.model_selection import select_projection_champion


def test_registry_keeps_underperforming_opportunity_model_in_shadow():
    registry = model_registry()
    challenger = next(model for model in registry["models"] if model["version"] == OPPORTUNITY_CHALLENGER_VERSION)

    assert registry["paid_mode"] == "champion_only"
    assert challenger["role"] == "challenger"
    assert challenger["paid_eligible"] is False


def test_projection_router_selects_chronologically_validated_baseline():
    selection = select_projection_champion(
        [20, 21, 19, 20, 22, 21, 20, 19, 21, 20, 18, 22, 20, 21, 19],
        opportunity_projection=30,
    )

    assert selection["method"] in {"season_average", "recent_10_average"}
    assert selection["projection"] < 23
    assert selection["challenger_projection"] == 30


def test_projection_router_can_select_leakage_free_opportunity_challenger():
    selection = select_projection_champion(
        [40, 38, 36, 34, 32, 30, 28, 26, 24, 22, 20, 18, 16, 14, 12],
        opportunity_projection=38,
        opportunity_validation={"samples": 10, "mae": 2.0},
    )

    assert selection["method"] == "opportunity_aware"
    assert selection["model_version"] == OPPORTUNITY_CHALLENGER_VERSION
    assert selection["projection"] == 38
