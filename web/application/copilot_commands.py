"""Bounded, read-only commands over existing EdgeIQ service responses."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from math import isfinite

from web.application.market_disagreement import market_disagreement_payload
from web.application.model_track_record import model_track_record
from web.schemas import CopilotQueryPayload

SPORTS = ("WNBA", "NCAAF", "NCAAM", "NCAAW", "NFL", "NBA", "MLB", "NHL", "MLS", "EPL", "UCL", "CS2")


@dataclass(frozen=True)
class QueryPlan:
    intent: str
    sport: str | None = None
    min_probability: float | None = None
    min_samples: int | None = None
    player: str = ""
    stat: str = ""
    evidence_filter: str = ""


def plan_command(payload: CopilotQueryPayload) -> QueryPlan | None:
    question = payload.question.casefold()
    sport = next((name for name in SPORTS if re.search(rf"\b{name.casefold()}\b", question)), None)
    if not sport and payload.sport != "All Sports":
        sport = payload.sport
    intent = None
    if any(term in question for term in ("my strongest historical", "my weakest historical", "personal edge", "my strongest segment")):
        intent = "personal_edge"
    elif "model track record" in question or "model validation" in question:
        intent = "model_track_record"
    elif any(term in question for term in ("most correlated risk", "concentration risk", "which open entries", "shared-leg risk")):
        intent = "portfolio_risk"
    elif any(term in question for term in ("changed the most", "since noon", "pick fall from", "recommendation timeline")):
        intent = "timeline" if payload.player.strip() or "pick fall from" in question else "slate_changes"
    elif any(term in question for term in ("stale evidence", "low fragility", "strongest counterargument")):
        intent = "evidence_review"
    elif any(term in question for term in ("props above", "recommendations above", "model probability with", "calibrated samples")):
        intent = "market_filter"
    elif "compare these" in question and "prop" in question:
        intent = "recommendation_compare"
    elif "what changed" in question and "slate" in question:
        intent = "timeline" if payload.player.strip() else "slate_changes"
    elif "disagreement" in question and "market" in question:
        intent = "market_disagreement"
    if not intent:
        return None
    probability_match = re.search(r"(?:above|over|at least)\s+(\d+(?:\.\d+)?)\s*%", question)
    samples_match = re.search(r"(?:at least|over|above)\s+(\d+)\s+(?:calibrated\s+)?samples?", question)
    return QueryPlan(
        intent=intent, sport=sport,
        min_probability=min(100.0, float(probability_match.group(1))) if probability_match else None,
        min_samples=min(5000, int(samples_match.group(1))) if samples_match else None,
        player=payload.player.strip(), stat=payload.stat.strip(),
        evidence_filter=("weakest" if "weakest historical" in question else
                         "stale" if "stale evidence" in question else
                         "counterargument" if "strongest counterargument" in question else "low_fragility"),
    )


def run_command(
    plan: QueryPlan,
    *,
    platform: str,
    briefing: Callable[[str, str | None], dict],
    portfolio: Callable[[], dict],
    personal_edge: Callable[[str], dict],
    timeline: Callable[..., dict],
    track_record: Callable[..., dict] = model_track_record,
) -> dict:
    if plan.intent == "portfolio_risk":
        data = portfolio()
        reasons = list(data.get("risk_reasons") or [])
        lines = [
            f"{data.get('concentration_risk', 'Unknown')} concentration risk across {data.get('pending_real_entries', 0)} pending paid cards.",
            f"Open stake: ${float(data.get('open_wager') or 0):.2f}. Shared exact markets: {int((data.get('shared_leg_failure_risk') or {}).get('repeated_props') or 0)}.",
        ]
        for entry in (data.get("top_risk_entries") or [])[:3]:
            lines.append(
                f"Entry #{entry.get('id')} ({entry.get('platform', 'provider unknown')}): "
                f"{entry.get('repeated_markets', 0)} repeated markets and {entry.get('shared_games', 0)} shared games."
            )
        lines.extend(str(reason) for reason in reasons[:2])
        return _result(plan.intent, lines, "portfolio-snapshot", "Pending paid portfolio snapshot", missing=[
            "The overlap index is not a measured correlation or loss probability.",
        ])
    if plan.intent == "personal_edge":
        data = personal_edge("real")
        strongest = data.get("weakest") if plan.evidence_filter == "weakest" else data.get("strongest")
        summary = data.get("summary") or {}
        lines = [f"Paid history contains {summary.get('verified_leg_decisions', 0)} verified leg decisions across {summary.get('settled_entries', 0)} settled cards."]
        if strongest:
            rank_label = "Lowest" if plan.evidence_filter == "weakest" else "Highest"
            lines.append(f"{rank_label} observed segment: {strongest['name']} ({strongest['wins']} wins, {strongest['losses']} losses; {strongest['decisions']} tracked placements).")
        elif data.get("truncated"):
            lines.append("The ledger window is incomplete, so strongest and weakest segments are withheld.")
        else:
            lines.append("No segment clears the minimum sample threshold in the complete history window.")
        return _result(plan.intent, lines, "personal-edge-snapshot", "Verified paid ledger summary", missing=[
            "Repeated placements are not independent games; past results do not predict future profit.",
        ])
    if plan.intent == "timeline":
        if not plan.player:
            return _result(plan.intent, ["Choose a player in the Player field to inspect saved recommendation changes."], missing=["Player identity is required; no timeline was queried."])
        data = timeline(player=plan.player, sport=plan.sport or "", stat=plan.stat, limit=30)
        events = data.get("events") or []
        if not events:
            return _result(plan.intent, [str(data.get("summary") or "No saved changes match this player and market.")], "timeline-snapshot", "Saved recommendation timeline")
        latest = events[-1]
        lines = [str(data.get("summary") or "Saved recommendation changes are available.")]
        changes = ", ".join(latest.get("changes") or []).replace("_", " ") or "initial saved state"
        lines.append(f"Latest saved difference for {latest.get('player', plan.player)} {latest.get('stat', '')}: {changes}.")
        lines.extend(str(reason) for reason in (latest.get("change_reasons") or [])[:2])
        return _result(plan.intent, lines, "timeline-snapshot", "Saved recommendation timeline", missing=["This view is limited to the latest 30 saved changes; it is not a full-slate change ranking."])
    if plan.intent == "model_track_record":
        if not plan.sport:
            return _result(plan.intent, ["Choose a sport for the model track record to keep the evidence window focused."], missing=["Sport filter is required; no prediction ledger was queried."])
        data = track_record(sport=plan.sport, stat=plan.stat)
        lines = [f"{plan.sport} has {data.get('settled_predictions', 0)} verified settled predictions in this record window."]
        for row in (data.get("versions") or [])[:3]:
            observed = row.get("actual_hit_rate")
            rate = f"{observed}%" if observed is not None else "unavailable"
            lines.append(f"{row.get('model_version', 'Model')} {row.get('platform', '')}: {row.get('settled_predictions', 0)} decisions, {rate} observed hit rate.")
        return _result(plan.intent, lines, "model-track-record", "Versioned prediction ledger", missing=[
            "The record is truncated; narrow sport/stat/provider filters before comparing models." if data.get("truncated") else "Historical track record does not establish future profit.",
        ])
    if plan.intent == "market_disagreement":
        data = market_disagreement_payload(briefing(platform, plan.sport))
        lines = [data["message"]]
        for row in data["rows"][:3]:
            difference = row["effective_difference"] if row["effective_difference"] is not None else row["raw_difference"]
            basis = "after calibration" if row["effective_difference"] is not None else "before calibration"
            lines.append(f"{row['player']} {row['direction']} {row['line']} {row['stat']}: {difference:+.1f} points {basis} versus {row['market_book_count']} paired sportsbook quotes.")
        return _result(plan.intent, lines, "briefing-market-snapshot", "Cached exact-line sportsbook comparison", missing=[
            "A probability difference is not expected value; payout and offer availability must be checked separately.",
        ])
    if plan.intent == "slate_changes":
        changes = (briefing(platform, plan.sport).get("slate_changes") or {})
        if not changes.get("available"):
            return _result(plan.intent, [str(changes.get("message") or "Refresh Today's briefing twice to compare the same day's displayed slate.")], missing=["No same-day saved comparison is available yet."])
        counts = changes.get("counts") or {}
        lines = [f"Since the previous refresh: {int(changes.get('event_count') or 0)} observed changes in displayed games and ranked props."]
        lines.append(f"{int(counts.get('new_recommendations') or 0)} newly ranked, {int(counts.get('upgrades') or 0)} upgrades, {int(counts.get('downgrades') or 0)} downgrades, {int(counts.get('invalidated') or 0)} invalidated.")
        lines.extend(f"{event.get('label', 'Recommendation')}: {event.get('detail', 'Changed')}" for event in (changes.get("events") or [])[:4])
        return _result(plan.intent, lines, "briefing-slate-comparison", "Saved same-day briefing comparison", missing=[
            "Only displayed games and ranked props were compared; this is not the full provider board.",
        ])
    if plan.intent == "recommendation_compare":
        return _result(plan.intent, ["Select the specific props to compare; the question alone does not identify four offers."], missing=["No matching verified comparison snapshot was supplied."])
    data = briefing(platform, plan.sport)
    rows = list(data.get("top_opportunities") or [])[:9]
    if plan.sport:
        rows = [row for row in rows if str(row.get("sport") or "").upper() == plan.sport.upper()]
    if plan.intent == "market_filter":
        if plan.min_probability is not None:
            rows = [row for row in rows if _meets_probability(row, plan.min_probability)]
        if plan.min_samples is not None:
            rows = [row for row in rows if _has_calibration_samples(row, plan.min_samples)]
    elif plan.intent == "evidence_review":
        # The same cached snapshot supplies the fragility and freshness fields shown on Today.
        rows = [row for row in rows if _matches_evidence_request(row, plan)]
        if plan.evidence_filter == "counterargument":
            rows.sort(key=lambda row: _number((row.get("counterargument") or {}).get("fragility_score")) or 0, reverse=True)
    lines = [_prop_line(row) for row in rows[:5]]
    if not lines:
        lines = ["No matching recommendations have the required evidence in the current cached briefing."]
    missing = ["Only the cached briefing's top opportunities were searched; refresh the briefing for newer offers."]
    if plan.min_samples is not None:
        missing.append("Sample filters use the matching calibration segment count, not the broader fallback count.")
    return _result(plan.intent, lines, "briefing-snapshot", "Cached daily briefing snapshot", missing=missing)


def _matches_evidence_request(row: dict, plan: QueryPlan) -> bool:
    # The caller's wording is intentionally not sent to SQL or an LLM-generated filter.
    if plan.evidence_filter == "stale":
        return (row.get("recommendation_freshness") or {}).get("status") == "expired"
    if plan.evidence_filter == "counterargument":
        return bool((row.get("counterargument") or {}).get("risk_factors"))
    return (row.get("counterargument") or {}).get("fragility_label") == "Low"


def _number(value: object) -> float | None:
    try:
        number = float(str(value))
        return number if isfinite(number) else None
    except (TypeError, ValueError):
        return None


def _meets_probability(row: dict, minimum: float) -> bool:
    value = _number(row.get("confidence"))
    return value is not None and value > minimum


def _sample_count(row: dict) -> int:
    try:
        return max(0, int((row.get("calibration_presentation") or {}).get("segment_sample_size") or 0))
    except (TypeError, ValueError):
        return 0


def _has_calibration_samples(row: dict, minimum: int) -> bool:
    calibration = row.get("calibration_presentation") or {}
    return calibration.get("status") in {"CALIBRATED", "PARTIAL", "DEGRADED"} and _sample_count(row) >= minimum


def _prop_line(row: dict) -> str:
    calibration = row.get("calibration_presentation") or {}
    samples = calibration.get("segment_sample_size")
    sample_label = (
        f", {_sample_count(row)} matching calibration samples ({calibration.get('label') or calibration.get('status') or 'status unavailable'})"
        if samples is not None else ", calibration samples unavailable"
    )
    risk = row.get("counterargument") or {}
    freshness = row.get("recommendation_freshness") or {}
    context = f" Fragility: {risk.get('fragility_label')}." if risk.get("fragility_label") else ""
    if risk.get("risk_factors"):
        context += " Main concern: " + str(risk["risk_factors"][0])[:160] + "."
    context += f" Evidence: {freshness.get('status')}." if freshness.get("status") else ""
    confidence = row.get("confidence")
    confidence_label = f"{confidence}%" if _number(confidence) is not None else "unavailable"
    return (
        f"{row.get('player', 'Player')} {row.get('direction', '')} {row.get('line', '')} {row.get('stat', '')} "
        f"({row.get('sport', '')}, {row.get('platform', '')}): {confidence_label} model confidence"
        f"{sample_label}.{context}"
    )


def _result(intent: str, lines: list[str], citation_id: str = "", label: str = "", *, missing: list[str] | None = None) -> dict:
    citations = [{"id": citation_id, "label": label, "source_url": "", "captured_at": "", "expires_at": ""}] if citation_id else []
    return {
        "intent": intent, "provider": "EdgeIQ Local", "model": "edgeiq-command-v1",
        "response": {
            "answer": lines[0], "recommendation": "Results from existing EdgeIQ evidence",
            "supporting_evidence": lines[1:5],
            "counterargument": "Descriptive app data does not guarantee a profitable outcome.",
            "missing_information": missing or [], "suggested_correction": "Review the cited source before acting.",
            "citations": [citation_id] if citation_id else [],
        },
        "citations": citations,
        "evidence_summary": {"intent": intent, "citation_count": len(citations), "citations": citations},
        "ai_error": None, "grounded": bool(citations),
    }
