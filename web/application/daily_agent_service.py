from __future__ import annotations

from collections.abc import Callable


def evaluate_provider_candidates(
    raw_props: list[dict], *, limit: int, analysis_limit: int | None,
    is_today: Callable[[dict], bool], eligibility: Callable[[dict], dict],
    prefilter_key: Callable, analyze: Callable[[dict], dict],
    candidate: Callable[[dict, dict], dict | None],
) -> tuple[list[dict], dict]:
    """Count actual pipeline stages without calling deferred rows rejected."""
    today = [row for row in raw_props if is_today(row)]
    eligible = [row for row in today if eligibility(row).get("eligible")]
    eligible.sort(key=prefilter_key, reverse=True)
    budget = max(1, int(analysis_limit)) if analysis_limit is not None else max(24, min(80, max(1, limit) * 2))
    selected = eligible[:budget]
    accepted = []
    for raw in selected:
        result = candidate(raw, analyze(raw))
        if result is not None:
            accepted.append(result)
    counts = {
        "retrieved": len(raw_props), "scheduled_today": len(today),
        "eligible": len(eligible), "analyzed": len(selected), "accepted": len(accepted),
        "deferred": len(eligible) - len(selected),
        "outside_today": len(raw_props) - len(today),
        "eligibility_rejected": len(today) - len(eligible),
        "analysis_rejected": len(selected) - len(accepted),
    }
    return accepted, counts


def daily_agent_summary(counts: dict | None, opportunities: list[dict]) -> dict:
    return {
        "coverage": counts,
        "coverage_available": counts is not None,
        "shortlist": {
            "displayed": len(opportunities),
            "paper_ready": sum((row.get("recommendation_eligibility") or {}).get("paper_ready") is True for row in opportunities),
            "paid_ready": sum((row.get("recommendation_eligibility") or {}).get("paid_ready") is True for row in opportunities),
        },
        "scope": "Selected provider candidate pool. Shortlist readiness is evaluated separately, not a whole-board pass rate.",
    }
