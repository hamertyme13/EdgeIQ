from types import SimpleNamespace

from web.application import high_probability_paper as samples


def _suggestion(*, source="verified_history_distribution", offer_type="standard", standard_line=20.5):
    props = [
        SimpleNamespace(
            forecast_snapshot={"source": source}, line_offer_type=offer_type,
            is_discounted_line=False, is_premium_line=False,
            line=20.5, standard_line=standard_line,
        )
        for _ in range(2)
    ]
    return SimpleNamespace(entry=SimpleNamespace(props=props))


def test_high_probability_sample_uses_saved_complete_card_probability(monkeypatch):
    monkeypatch.setattr(samples, "prepare_entry_analysis", lambda *args, **kwargs: (
        {"all_hit_probability": 60.0}, {},
    ))
    assert samples.evaluated_standard_card_probability(_suggestion()) == 60.0

    monkeypatch.setattr(samples, "prepare_entry_analysis", lambda *args, **kwargs: (
        {"all_hit_probability": 59.99}, {},
    ))
    assert samples.evaluated_standard_card_probability(_suggestion()) is None


def test_high_probability_sample_rejects_market_prior_and_adjusted_lines(monkeypatch):
    monkeypatch.setattr(samples, "prepare_entry_analysis", lambda *args, **kwargs: (
        {"all_hit_probability": 90.0}, {},
    ))
    assert samples.evaluated_standard_card_probability(_suggestion(source="market_prior")) is None
    assert samples.evaluated_standard_card_probability(_suggestion(offer_type="goblin")) is None
    assert samples.evaluated_standard_card_probability(_suggestion(standard_line=22.5)) is None
    assert samples.standard_line_offer({"line": 20.5, "line_offer_type": "standard", "standard_line": 20.5})
    assert not samples.standard_line_offer({"line": 18.5, "line_offer_type": "goblin", "standard_line": 20.5})
    assert not samples.standard_line_offer({"line": 20.5, "adjusted_line": True})
