from __future__ import annotations

import json
import re
from collections.abc import Callable

from services.ollama_client import ollama_model, ollama_structured
from web.schemas import CopilotQueryPayload, ModelEvaluationPayload, RecommendationExplainPayload

ANSWER_SCHEMA = {
    "type": "object",
    "properties": {
        "answer": {"type": "string"},
        "recommendation": {"type": "string"},
        "supporting_evidence": {"type": "array", "items": {"type": "string"}},
        "counterargument": {"type": "string"},
        "missing_information": {"type": "array", "items": {"type": "string"}},
        "suggested_correction": {"type": "string"},
        "citations": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "answer", "recommendation", "supporting_evidence", "counterargument",
        "missing_information", "suggested_correction", "citations",
    ],
}


def copilot_query_payload(
    payload: CopilotQueryPayload,
    *,
    player_research: Callable[[str, str, str | None, str, float | None], dict],
    loss_review: Callable[[], dict],
    briefing: Callable[[str, str | None], dict],
    portfolio: Callable[[], dict],
) -> dict:
    intent = _intent(payload)
    if intent == "player_research":
        evidence = player_research(
            payload.player, payload.stat,
            None if payload.sport == "All Sports" else payload.sport,
            payload.platform, payload.line,
        )
    elif intent == "outcome_learning":
        evidence = loss_review()
    elif intent == "portfolio":
        evidence = portfolio()
    else:
        evidence = briefing(payload.platform, None if payload.sport == "All Sports" else payload.sport)
    bundle = _evidence_bundle(intent, evidence)
    answer, error = _grounded_answer(payload.question, bundle)
    return {
        "intent": intent,
        "provider": "Ollama" if answer else "EdgeIQ Local",
        "model": ollama_model() if answer else "edgeiq-grounded-fallback-v1",
        "response": answer or _fallback_answer(intent, bundle),
        "citations": _public_citations(bundle),
        "evidence_summary": _evidence_manifest(bundle),
        "ai_error": error,
        "grounded": True,
    }


def explain_recommendation_payload(payload: RecommendationExplainPayload) -> dict:
    selected = _compact_suggestion(payload.suggestion)
    alternatives = [_compact_suggestion(row) for row in payload.alternatives[:3]]
    evidence = {"selected": selected, "alternatives": alternatives}
    bundle = _evidence_bundle("recommendation", evidence)
    answer, error = _grounded_answer(payload.question, bundle)
    return {
        "provider": "Ollama" if answer else "EdgeIQ Local",
        "model": ollama_model() if answer else "edgeiq-grounded-fallback-v1",
        "response": answer or _fallback_answer("recommendation", bundle),
        "citations": _public_citations(bundle),
        "grounded": True,
        "ai_error": error,
    }


def model_evaluation_payload(payload: ModelEvaluationPayload) -> dict:
    model = payload.model.strip() or ollama_model()
    evidence = {
        "selected": {
            "grade": "B", "action": "Paper only",
            "props": [{"player": "Test Player", "stat": "Points", "direction": "Over", "line": 19.5, "confidence": 57.0}],
        }
    }
    bundle = _evidence_bundle("model_evaluation", evidence)
    answer, error = _grounded_answer("Explain this test card without adding facts.", bundle, model=model)
    passed = bool(answer and set(answer.get("citations") or []).issubset({row["id"] for row in bundle["citations"]}))
    return {
        "model": model,
        "passed": passed,
        "structured_output": bool(answer),
        "citation_valid": passed,
        "error": error,
        "response": answer,
        "note": "A model must pass structured-output and citation checks before use in paid recommendation explanations.",
    }


def _intent(payload: CopilotQueryPayload) -> str:
    text = payload.question.lower()
    if payload.player and payload.stat:
        return "player_research"
    if any(token in text for token in ("loss", "lost", "winning", "win versus", "model learn")):
        return "outcome_learning"
    if any(token in text for token in ("portfolio", "exposure", "bankroll", "shared leg")):
        return "portfolio"
    return "daily_briefing"


def _evidence_bundle(intent: str, evidence: dict) -> dict:
    compact = _compact_for_intent(intent, evidence)
    citations = []
    if intent == "player_research":
        for row in (compact.get("evidence") or [])[:20]:
            citations.append({
                "id": str(row.get("id") or ""),
                "label": f"{row.get('source') or 'EdgeIQ'} · {row.get('type') or 'evidence'}",
                "source_url": str(row.get("source_url") or ""),
                "captured_at": str(row.get("captured_at") or ""),
                "expires_at": str(row.get("expires_at") or ""),
                "data": row.get("payload") or {},
            })
        if not citations:
            for index, row in enumerate(compact.get("chart") or [], start=1):
                citations.append({"id": f"final-{index}", "label": str(row.get("game") or row.get("game_date") or "Final stat"), "data": row})
        if compact.get("recommendation"):
            citations.append({"id": "current-market", "label": "Current provider market", "data": compact["recommendation"]})
    elif intent == "outcome_learning":
        citations = [
            {"id": f"outcome-{index}", "label": str(row.get("result") or "Settled entry"), "data": row}
            for index, row in enumerate((compact.get("entries") or [])[:10], start=1)
        ]
    elif intent in {"recommendation", "model_evaluation"}:
        citations = [{"id": "selected-card", "label": "Selected recommendation snapshot", "data": compact.get("selected") or compact}]
        citations.extend(
            {"id": f"alternative-{index}", "label": "Alternative recommendation snapshot", "data": row}
            for index, row in enumerate(compact.get("alternatives") or [], start=1)
        )
    else:
        citation_id = "briefing-snapshot" if intent == "daily_briefing" else f"{intent}-snapshot"
        citations = [{"id": citation_id, "label": f"Current {intent.replace('_', ' ')} snapshot", "data": compact}]
    return {"intent": intent, "summary": compact, "citations": citations}


def _compact_for_intent(intent: str, evidence: dict) -> dict:
    if intent == "daily_briefing":
        return {
            "as_of": evidence.get("as_of"),
            "headline": evidence.get("headline"),
            "summary": _compact(evidence.get("summary") or {}),
            "loss_protection": _compact(evidence.get("loss_protection") or {}),
            "top_opportunities": [
                _pick(row, "player", "sport", "stat", "direction", "line", "projection", "confidence", "grade", "platform", "game", "data_strength")
                for row in (evidence.get("top_opportunities") or [])[:5]
            ],
            "games_today": [
                _pick(row, "matchup", "game", "sport", "start_time", "status", "best_prop", "best_value_prop", "highest_confidence", "injuries")
                for row in (evidence.get("games_today") or [])[:5]
            ],
            "suggested_entries": [
                _compact_suggestion(row) for row in (evidence.get("suggested_entries") or [])[:3]
            ],
            "rules": [str(row)[:240] for row in (evidence.get("rules") or [])[:5]],
            "recommendation_snapshot_id": evidence.get("recommendation_snapshot_id"),
            "model_version": evidence.get("model_version"),
        }
    if intent == "portfolio":
        return _compact({
            key: evidence.get(key)
            for key in (
                "summary", "pending_entries", "total_exposure", "player_exposure", "game_exposure",
                "team_exposure", "stat_exposure", "direction_exposure", "warnings", "shared_leg_risk",
                "correlation_score", "suggested_replacements",
            )
            if key in evidence
        })
    return _compact(evidence)


def _evidence_manifest(bundle: dict) -> dict:
    return {
        "intent": bundle["intent"],
        "citation_count": len(bundle["citations"]),
        "citations": [{"id": row["id"], "label": row["label"]} for row in bundle["citations"]],
    }


def _public_citations(bundle: dict) -> list[dict]:
    return [{
        "id": row["id"], "label": row["label"],
        "source_url": row.get("source_url", ""),
        "captured_at": row.get("captured_at", ""),
        "expires_at": row.get("expires_at", ""),
    } for row in bundle["citations"]]


def _pick(row: dict, *keys: str) -> dict:
    return {key: _compact(row.get(key)) for key in keys if row.get(key) not in (None, "", [], {})}


def _grounded_answer(question: str, bundle: dict, *, model: str | None = None) -> tuple[dict | None, str | None]:
    citation_ids = [row["id"] for row in bundle["citations"]]
    messages = [
        {
            "role": "system",
            "content": (
                "You are EdgeIQ's grounded local research copilot. Use only the JSON evidence. "
                "Do not invent or recalculate numbers, players, injuries, lines, odds, or outcomes. "
                "Citations must be selected only from citation_ids. If evidence is missing, say so. "
                "Matchup history describes the player's results, never opponent defense. Return only the requested JSON schema."
            ),
        },
        {"role": "user", "content": json.dumps({"question": question, "citation_ids": citation_ids, "evidence": bundle}, default=str)},
    ]
    schema = json.loads(json.dumps(ANSWER_SCHEMA))
    schema["properties"]["citations"]["items"]["enum"] = citation_ids
    answer, error = ollama_structured(messages, schema, model=model, timeout=25)
    if not answer:
        return None, error
    used = answer.get("citations") or []
    if not used or not set(used).issubset(set(citation_ids)):
        return None, "Ollama returned an unsupported citation, so EdgeIQ used its grounded fallback."
    if _unsupported_numbers(answer, bundle):
        return None, "Ollama introduced a number that was not in the evidence, so EdgeIQ used its grounded fallback."
    if _unsupported_matchup_claim(answer):
        return None, "Ollama misread matchup evidence, so EdgeIQ used its grounded fallback."
    answer["citations"] = list(dict.fromkeys(used))
    return answer, None


def _unsupported_numbers(answer: dict, bundle: dict) -> bool:
    generated = {token for token in re.findall(r"\d+(?:\.\d+)?", json.dumps(answer)) if float(token) > 10}
    evidence = set(re.findall(r"\d+(?:\.\d+)?", json.dumps(bundle, default=str)))
    return bool(generated - evidence)


def _unsupported_matchup_claim(answer: dict) -> bool:
    text = json.dumps(answer).lower()
    patterns = (
        r"opponent(?:'s)? (?:average|mean|minutes|opportunities|performance|defense|defensive)",
        r"use .{0,80} as (?:the |a )?(?:new )?opponent",
        r"home team.{0,100}opponent",
        r"opponent allows?",
    )
    return any(re.search(pattern, text) for pattern in patterns)


def _fallback_answer(intent: str, bundle: dict) -> dict:
    citation_ids = [row["id"] for row in bundle["citations"]]
    return {
        "answer": f"EdgeIQ assembled the current {intent.replace('_', ' ')} evidence without adding outside claims.",
        "recommendation": "Use the verified evidence and keep unsupported or thin-history decisions in paper mode.",
        "supporting_evidence": [row["label"] for row in bundle["citations"][:3]],
        "counterargument": "The available sample may not capture late injury, role, or lineup changes.",
        "missing_information": ["Any field absent from the evidence snapshot remains unknown."],
        "suggested_correction": "Choose the stronger provider-backed alternative when the selected card has weak evidence.",
        "citations": citation_ids[:3],
    }


def _compact_suggestion(row: dict) -> dict:
    entry = row.get("entry") or {}
    return {
        key: row.get(key)
        for key in ("grade", "action", "score", "risk_tier", "model_trust", "warnings", "snapshot_id")
    } | {
        "platform": entry.get("platform"),
        "props": [
            {key: prop.get(key) for key in ("player", "sport", "stat", "direction", "line", "projection", "confidence", "edge", "game", "data_strength")}
            for prop in (entry.get("props") or [])
        ],
    }


def _compact(value):
    if isinstance(value, dict):
        return {str(key): _compact(item) for key, item in value.items() if key not in {"raw_ai", "feature_snapshot", "audit_snapshot"}}
    if isinstance(value, list):
        return [_compact(item) for item in value[:10]]
    if isinstance(value, str) and len(value) > 600:
        return value[:600]
    return value
