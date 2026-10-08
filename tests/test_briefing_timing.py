from web.application.briefing_timing import BriefingTiming


def test_briefing_timing_records_repeated_stages_and_total():
    timing = BriefingTiming()
    with timing.stage("provider_fetch_and_board_snapshot"):
        pass
    with timing.stage("provider_fetch_and_board_snapshot"):
        pass
    with timing.stage("confirmed_prop_analysis"):
        pass
    result = timing.snapshot()
    assert result["provider_fetch_and_board_snapshot"] >= 0
    assert result["confirmed_prop_analysis"] >= 0
    assert result["total_ms"] >= result["provider_fetch_and_board_snapshot"]
