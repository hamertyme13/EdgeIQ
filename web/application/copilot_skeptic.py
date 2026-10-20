"""Deterministic challenge view over one exact cached recommendation."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from web.schemas import CopilotQueryPayload

MAX_SNAPSHOT_AGE = timedelta(minutes=30)


def skeptic_response(
    payload: CopilotQueryPayload,
    cached_briefing: Callable[[str, str | None], dict],
    *,
    now: datetime | None = None,
) -> dict:
    if payload.selected_recommendation_index is None or not payload.selected_snapshot_id:
        return _unavailable("Select a recommendation on Today before challenging it.")
    try:
        briefing = cached_briefing(payload.platform, None if payload.sport == "All Sports" else payload.sport)
    except Exception:
        return _unavailable("The saved briefing could not be loaded. Try again shortly.")
    if briefing.get("recommendation_snapshot_id") != payload.selected_snapshot_id:
        return _unavailable("The displayed briefing has changed. Refresh Today and select the prop again.")
    try:
        captured = datetime.fromisoformat(str(briefing.get("as_of") or "").replace("Z", "+00:00"))
    except ValueError:
        return _unavailable("The briefing timestamp is unavailable. Refresh Today before reviewing this prop.")
    current = now or datetime.now(UTC)
    if (captured.tzinfo is None or captured > current
            or current - captured > MAX_SNAPSHOT_AGE or (briefing.get("cache") or {}).get("stale")):
        return _unavailable("This briefing is no longer current. Refresh Today before reviewing the prop.")
    rows = briefing.get("top_opportunities") or []
    index = payload.selected_recommendation_index
    if index >= len(rows):
        return _unavailable("This prop is no longer in the displayed briefing. Refresh Today and select it again.")
    row = rows[index]
    identity = payload.selected_recommendation_identity
    fields = ("player", "sport", "stat", "direction", "line", "platform", "game")
    if any(key not in identity or str(row.get(key) or "") != identity[key] for key in fields):
        return _unavailable("The selected prop has changed since the page loaded. Refresh Today and select it again.")
    freshness = row.get("recommendation_freshness") or {}
    if freshness.get("status") == "expired":
        return _unavailable("The provider offer has expired. Refresh Today before reviewing this line.")
    risk = row.get("counterargument") or {}
    calibration = row.get("calibration_presentation") or {}
    sensitivity = row.get("sensitivity") or {}
    receipt = row.get("decision_receipt") or {}
    risks = [str(item) for item in (risk.get("risk_factors") or [])[:4] if item]
    invalidating = [str(item) for item in (risk.get("invalidating_conditions") or [])[:4] if item]
    if sensitivity.get("status") == "model_only" and sensitivity.get("first_tested_failing_line") is not None:
        invalidating.append(f"The tested model falls below its research threshold at line {sensitivity['first_tested_failing_line']}.")
    if freshness.get("status") != "fresh":
        invalidating.append("The exact provider offer has not been confirmed fresh.")
    if not risks:
        risks = ["No specific failure factor was recorded for this snapshot; that does not mean the prop is low-risk."]
    if not invalidating:
        invalidating = ["No numeric invalidation boundary was recorded. Recheck the exact line, role, and payout before acting."]
    missing = []
    if calibration.get("status") != "CALIBRATED":
        missing.append("This sport/stat/provider segment does not have a fully calibrated probability here.")
    if sensitivity.get("status") != "model_only":
        missing.append("A tested line-sensitivity boundary is unavailable.")
    if receipt.get("market_probability") is None:
        missing.append("No exact-line market probability was verified in this snapshot.")
    if not missing:
        missing.append("Late changes after this snapshot remain unknown; confirm the offer in the provider app.")
    player = str(row.get("player") or "This player")
    stat = str(row.get("stat") or "this stat")
    answer = f"The strongest recorded case against {player} {row.get('direction') or ''} {row.get('line')} {stat} is: {risks[0]}"
    citation_id = "selected-recommendation-snapshot"
    return {
        "intent": "skeptic", "provider": "EdgeIQ Local", "model": "edgeiq-skeptic-v1",
        "response": {
            "answer": answer,
            "recommendation": "Recheck before paid use" if (row.get("recommendation_eligibility") or {}).get("paid_ready") else "Keep this paper-first",
            "supporting_evidence": risks[1:4], "counterargument": risks[0],
            "missing_information": missing[:4], "suggested_correction": invalidating[0],
            "citations": [citation_id],
        },
        "invalidating_conditions": invalidating[:4],
        "evidence": {
            "player": player, "sport": row.get("sport"), "stat": stat,
            "direction": row.get("direction"), "line": row.get("line"),
            "fragility": risk.get("fragility_label") or "Unavailable",
            "calibration_status": calibration.get("status") or "Unavailable",
            "segment_sample_size": calibration.get("segment_sample_size"),
            "freshness": freshness.get("status") or "Unknown",
            "as_of": captured.isoformat(),
        },
        "citations": [{"id": citation_id, "label": "Selected cached recommendation and recorded risks",
                       "source_url": "", "captured_at": captured.isoformat(), "expires_at": ""}],
        "grounded": True, "ai_error": None,
    }


def _unavailable(message: str) -> dict:
    return {
        "intent": "skeptic", "provider": "EdgeIQ Local", "model": "edgeiq-skeptic-v1",
        "response": {"answer": message, "recommendation": "Refresh or select a prop",
                     "supporting_evidence": [], "counterargument": "",
                     "missing_information": [message], "suggested_correction": "", "citations": []},
        "invalidating_conditions": [], "evidence": {}, "citations": [],
        "grounded": False, "ai_error": None,
    }
