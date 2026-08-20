from __future__ import annotations


def recommendation_eligibility(
    prop: dict,
    *,
    trust_score: float,
    model_paid_enabled: bool,
) -> dict:
    """Classify a recommendation without presenting research evidence as paid-ready."""
    confidence = float(prop.get("confidence") or 0.0)
    freshness = prop.get("recommendation_freshness") or {}
    expired = freshness.get("status") == "expired"
    paper_blocks: list[str] = []
    paid_blocks: list[str] = []
    warnings: list[str] = []

    if not prop.get("market_supported"):
        paper_blocks.append("This stat does not have a verified sportsbook-market mapping.")
    if not prop.get("end_to_end_confirmed"):
        paper_blocks.append("EdgeIQ cannot yet match this offer to an official final-stat market.")
    if prop.get("line") in (None, "") or float(prop.get("line") or 0.0) <= 0:
        paper_blocks.append("A current provider line is required.")
    if confidence < 52.0:
        paper_blocks.append("Model probability is below the 52% research threshold.")
    if expired:
        paper_blocks.append("The recommendation snapshot has expired and must be refreshed.")

    paper_ready = not paper_blocks
    if not paper_ready:
        paid_blocks.extend(paper_blocks)
    if not prop.get("provider_backed"):
        paid_blocks.append("The projection is auto-generated rather than provider-backed.")
    if not prop.get("forecast_paid_eligible"):
        paid_blocks.append("This sport/stat segment has not cleared paid-model evidence thresholds.")
    if trust_score < 64.0:
        paid_blocks.append(f"Model Trust is {trust_score:.0f}; paid consideration requires 64 or higher.")
    if not model_paid_enabled:
        paid_blocks.append("The current model release has not cleared the paid recommendation gate.")

    if prop.get("adjusted_line"):
        warnings.append("Confirm the adjusted-line payout and allowed direction in the provider app.")
    if not (prop.get("decision_receipt") or {}).get("market_probability"):
        warnings.append("No independent market probability is available for comparison.")

    paid_ready = not paid_blocks
    if paid_ready:
        label = "Paid-ready"
        status = "paid_ready"
    elif paper_ready:
        label = "Paper only"
        status = "paper_only"
    else:
        label = "Research only"
        status = "research_only"
    return {
        "status": status,
        "label": label,
        "paper_ready": paper_ready,
        "paid_ready": paid_ready,
        "paper_blocks": paper_blocks,
        "paid_blocks": paid_blocks,
        "warnings": warnings,
    }
