from pathlib import Path

APP_JS = Path(__file__).resolve().parents[1] / "web" / "static" / "app.js"


def test_research_and_refresh_events_do_not_record_freeform_text():
    source = APP_JS.read_text()
    ask = source.split("async function askCopilot() {", 1)[1].split("function renderCopilotResponse", 1)[0]
    refresh = source.split("async function refreshTodayProviders() {", 1)[1].split("async function loadAdvantageCenter", 1)[0]

    assert 'trackProductEvent("ask_edgeiq_query", "copilot", "", context)' in ask
    assert 'trackProductEvent("ask_edgeiq_result", "copilot", "", {' in ask
    assert 'trackProductEvent("ask_edgeiq_failed", "copilot", "", context)' in ask
    assert 'question: $("copilot-question").value' in ask
    assert 'trackProductEvent("provider_refresh_failed", "provider", "", { platform, sport })' in refresh
    assert "error.message" not in refresh


def test_recommendation_evidence_and_timeline_are_counted():
    source = APP_JS.read_text()

    assert 'trackProductEvent("evidence_expanded", "recommendation", "", {' in source
    assert 'trackProductEvent("timeline_viewed", "recommendation", "", {' in source
