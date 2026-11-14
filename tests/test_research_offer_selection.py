from web.application.research_service import select_research_offer


def test_exact_line_precedes_higher_confidence_different_line():
    offers = [
        {"line": 20.5, "confidence": 0.9, "data_quality": {"score": 90}},
        {"line": 19.5, "confidence": 0.6, "data_quality": {"score": 60}},
    ]
    assert select_research_offer(offers, 19.5) is offers[1]
    assert select_research_offer(offers, 21.5) is offers[0]
    assert select_research_offer(offers, None) is offers[0]
    assert select_research_offer([], 19.5) is None


def test_exact_line_uses_quality_to_break_confidence_tie():
    offers = [
        {"line": 19.5, "confidence": 0.6, "data_quality": {"score": 40}},
        {"line": 19.5, "confidence": 0.6, "data_quality": {"score": 70}},
    ]
    assert select_research_offer(offers, 19.5) is offers[1]
