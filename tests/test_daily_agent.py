from web.application.daily_agent_service import daily_agent_summary, evaluate_provider_candidates


def test_deferred_candidates_are_not_analyzed_or_rejected():
    rows = [{"id": i} for i in range(10)]
    analyzed = []
    def analyze(row):
        analyzed.append(row["id"])
        return row
    accepted, counts = evaluate_provider_candidates(
        rows, limit=2, analysis_limit=3,
        is_today=lambda row: row["id"] < 8,
        eligibility=lambda row: {"eligible": row["id"] < 6},
        prefilter_key=lambda row: row["id"], analyze=analyze,
        candidate=lambda raw, result: result if raw["id"] != 5 else None,
    )
    assert analyzed == [5, 4, 3]
    assert len(accepted) == 2
    assert counts == {"retrieved": 10, "scheduled_today": 8, "eligible": 6,
                      "analyzed": 3, "accepted": 2, "deferred": 3,
                      "outside_today": 2, "eligibility_rejected": 2, "analysis_rejected": 1}


def test_missing_counts_do_not_claim_zero_scans():
    result = daily_agent_summary(None, [{"recommendation_eligibility": {"paper_ready": True}}])
    assert result["coverage"] is None
    assert not result["coverage_available"]
    assert result["shortlist"] == {"displayed": 1, "paper_ready": 1, "paid_ready": 0}
