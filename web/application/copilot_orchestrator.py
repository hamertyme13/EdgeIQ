"""Fixed, bounded read-only workflows for questions needing two evidence sources."""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from utils.config_bounds import bounded_env_int
from utils.entity_normalization import canonical_person_key
from web.application.copilot_commands import QueryPlan
from web.application.copilot_tools import ToolContext, invoke_tool

MAX_TOOL_CALLS = 2
MAX_RESULT_ROWS = 3
MAX_ELAPSED_SECONDS = 6.0


@dataclass
class _Budget:
    context: ToolContext
    started: float = field(default_factory=time.monotonic)
    calls: int = 0

    def read(self, name: str, arguments: dict) -> dict:
        if self.calls >= bounded_env_int("EDGEIQ_COPILOT_MAX_TOOL_CALLS", MAX_TOOL_CALLS, 1, MAX_TOOL_CALLS) or time.monotonic() - self.started >= MAX_ELAPSED_SECONDS:
            raise TimeoutError("The research budget was reached")
        self.calls += 1
        result = invoke_tool(name, arguments, self.context)
        if time.monotonic() - self.started >= MAX_ELAPSED_SECONDS:
            raise TimeoutError("The research budget was reached")
        return result


def run_workflow(plan: QueryPlan, question: str, platform: str, context: ToolContext) -> dict | None:
    """Map validated intent to a server-owned graph; the model cannot choose tools."""
    lowered = question.casefold()
    if plan.intent == "model_track_record" and any(word in lowered for word in ("today", "current", "tonight")):
        return _slate_validation(plan, platform, _Budget(context))
    if plan.intent == "portfolio_risk" and any(word in lowered for word in ("recommendation", "prop", "candidate")):
        return _portfolio_shortlist(plan, platform, _Budget(context))
    return None


def _slate_validation(plan: QueryPlan, platform: str, budget: _Budget) -> dict:
    if not plan.sport:
        return _answer("slate_validation", ["Choose a sport to compare today's slate with settled model results."],
                       [], budget.calls, ["A sport is required before querying the prediction ledger."])
    try:
        slate = budget.read("cached_briefing", {"platform": platform, "sport": plan.sport})
    except Exception as exc:
        return _failed("slate_validation", budget.calls, exc)
    rows = [row for row in slate.get("top_opportunities") or [] if row.get("sport") == plan.sport]
    if (slate.get("cache") or {}).get("stale"):
        return _answer("slate_validation", ["The saved briefing has expired. Refresh it before comparing today's slate with historical results."],
                       ["briefing-snapshot"], budget.calls, ["No current-slate claim was made from the expired cache."])
    try:
        record = budget.read("model_track_record", {"sport": plan.sport, "stat": plan.stat})
    except Exception:
        return _answer("slate_validation", [f"The cached {plan.sport} slate has {len(rows)} displayed opportunities."],
                       ["briefing-snapshot"], budget.calls,
                       ["The settled model record could not be loaded; no validation claim is available."])
    settled = int(record.get("settled_predictions") or 0)
    lines = [f"The cached {plan.sport} slate has {len(rows)} displayed opportunities; the settled model record has {settled} predictions."]
    for row in rows[:MAX_RESULT_ROWS]:
        confidence = f"{row['confidence']}%" if row.get("confidence") is not None else "unavailable"
        lines.append(f"{row.get('player') or 'Player'} {row.get('stat') or 'stat unavailable'}: today's displayed model confidence is {confidence}.")
    return _answer("slate_validation", lines, ["briefing-snapshot", "model-track-record"], budget.calls, [
        "These settled predictions are not necessarily the same players or markets as today's slate.",
        "Past results do not establish that a current offer is profitable or still available.",
    ])


def _portfolio_shortlist(plan: QueryPlan, platform: str, budget: _Budget) -> dict:
    try:
        portfolio = budget.read("portfolio_risk", {})
    except Exception as exc:
        return _failed("portfolio_shortlist", budget.calls, exc)
    if "pending_real_entries" not in portfolio:
        return _answer("portfolio_shortlist", ["Current paid exposure is unavailable; I cannot screen candidate overlap."],
                       [], budget.calls, ["Refresh the portfolio before reviewing candidate props."])
    try:
        slate = budget.read("cached_briefing", {"platform": platform, "sport": plan.sport})
    except Exception:
        return _answer("portfolio_shortlist", ["Paid exposure loaded, but today's cached recommendations did not."],
                       ["portfolio-snapshot"], budget.calls, ["Refresh the briefing before looking for candidates."])
    if (slate.get("cache") or {}).get("stale"):
        return _answer("portfolio_shortlist", ["The saved briefing has expired; no current candidates were screened."],
                       ["portfolio-snapshot", "briefing-snapshot"], budget.calls,
                       ["Refresh the briefing before looking for candidates."])
    exposed = {canonical_person_key(row.get("key") or row.get("label")) for row in portfolio.get("top_players") or []}
    candidates = []
    for row in slate.get("top_opportunities") or []:
        if plan.sport and row.get("sport") != plan.sport:
            continue
        key = canonical_person_key(row.get("player"))
        if not key or key in exposed or (row.get("recommendation_freshness") or {}).get("status") == "expired":
            continue
        candidates.append(row)
        if len(candidates) == MAX_RESULT_ROWS:
            break
    lines = [f"{len(candidates)} research leads from the cached slate are outside the portfolio's displayed top player exposures."]
    lines.extend(f"{row.get('player')} {row.get('direction') or ''} {row.get('line') or ''} {row.get('stat') or ''} ({row.get('platform') or platform})." for row in candidates)
    return _answer("portfolio_shortlist", lines, ["portfolio-snapshot", "briefing-snapshot"], budget.calls, [
        "Only the portfolio's top player exposures are available here; other player, game, and exact-market overlap may remain.",
        "Run the complete entry analysis before placement. These leads are not cleared paid picks or verified EV.",
    ])


def _failed(intent: str, calls: int, error: Exception) -> dict:
    return _answer(intent, ["The requested evidence could not be loaded right now."], [], calls,
                   [f"The {error.__class__.__name__} interrupted this read-only workflow; try again later."])


def _answer(intent: str, lines: list[str], citation_ids: list[str], calls: int, missing: list[str]) -> dict:
    labels = {"briefing-snapshot": "Cached daily briefing", "portfolio-snapshot": "Pending paid portfolio",
              "model-track-record": "Settled versioned predictions"}
    citations = [{"id": key, "label": labels[key], "source_url": "", "captured_at": "", "expires_at": ""}
                 for key in citation_ids]
    return {
        "intent": intent, "provider": "EdgeIQ Local", "model": "edgeiq-workflow-v1",
        "response": {"answer": lines[0], "recommendation": "Research summary",
                     "supporting_evidence": lines[1:4], "counterargument": "These observations do not guarantee a winning entry.",
                     "missing_information": missing, "suggested_correction": "Review current offers and complete entry analysis.",
                     "citations": citation_ids},
        "citations": citations, "evidence_summary": {"intent": intent, "citation_count": len(citations), "citations": citations},
        "ai_error": None, "grounded": bool(citations),
        "execution": {"workflow": intent, "tool_calls": calls, "model_calls": 0},
    }
