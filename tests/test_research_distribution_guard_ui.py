from pathlib import Path


def test_research_projection_guard_applies_to_every_stat():
    source = (Path(__file__).resolve().parents[1] / "web/static/app.js").read_text()
    assert 'const verifiedDistribution = data.forecast?.source === "verified_history_distribution"' in source
    assert "An independent ${escapeHtml(data.stat)} projection is unavailable" in source
    assert 'verifiedDistribution ? `${escapeHtml(distribution.uncertainty_level' in source
    assert "nbaMarketPrior" not in source
