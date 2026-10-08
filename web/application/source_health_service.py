"""Source-level operational evidence with explicit measurement scopes."""
from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime, timedelta

from sqlalchemy import func

from repository.database import SessionLocal
from repository.models.prediction_record_model import PredictionRecordModel
from repository.models.research_evidence_model import ResearchEvidenceModel
from repository.models.settlement_audit_model import SettlementAuditModel
from utils.time import utc_now

_FINAL_SOURCES = {"espn", "mlb_statsapi", "nba_api", "pandascore", "statshawk"}
_RESEARCH_ALIASES = {
    "espn": "ESPN public", "prizepicks": "PrizePicks", "underdog": "Underdog",
    "sportsdataio": "SportsDataIO", "newsapi": "NewsAPI", "openweather": "OpenWeather",
    "statshawk": "StatsHawk", "pandascore": "PandaScore",
}
_FINAL_AUDIT_ALIASES = {
    "espn": "ESPN public", "espn official box score": "ESPN public",
    "espn_verified_dnp": "ESPN public", "statshawk": "StatsHawk",
    "pandascore": "PandaScore", "nba_api": "NBA Stats",
    "sportsdataio": "SportsDataIO",
}
_OFFER_SOURCES = {"PrizePicks", "Underdog", "DraftKings Pick6", "Sleeper"}


def _time(value: object) -> datetime | None:
    if isinstance(value, datetime):
        stamp = value
    else:
        try:
            stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return None
    return stamp.replace(tzinfo=UTC) if stamp.tzinfo is None else stamp.astimezone(UTC)


def _percentage(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator * 100, 1) if denominator else None


def summarize_source_health(
    providers: list[dict], facts: list[tuple], audits: list[tuple], predictions: list[tuple],
    *, now: datetime, truncated: bool = False,
) -> dict:
    research: dict[str, dict[str, int]] = defaultdict(lambda: {"facts": 0, "uses": 0, "linked_outcomes": 0})
    for source, count, uses, links in facts:
        name = _RESEARCH_ALIASES.get(str(source or "").lower())
        if name:
            research[name]["facts"] += int(count or 0)
            research[name]["uses"] += int(uses or 0)
            research[name]["linked_outcomes"] += int(links or 0)

    latest_audit: dict[tuple[str, int], str] = {}
    for audit in audits:
        source, status, prop_id = audit[:3]
        name = _FINAL_AUDIT_ALIASES.get(str(source or "").lower())
        if name and prop_id is not None:
            latest_audit[name, int(prop_id)] = str(status or "").lower()
    attempted: dict[str, int] = defaultdict(int)
    verified: dict[str, int] = defaultdict(int)
    for (name, _), status in latest_audit.items():
        attempted[name] += 1
        if status == "verified":
            verified[name] += 1

    tracked: dict[str, set[str]] = defaultdict(set)
    settled: dict[str, set[str]] = defaultdict(set)
    cutoff = now - timedelta(hours=24)
    for platform, market_key, game_time, outcome, final_source in predictions:
        name = str(platform or "")
        game = _time(game_time)
        if name not in _OFFER_SOURCES or not market_key or game is None or game > cutoff:
            continue
        tracked[name].add(str(market_key))
        if outcome in {"Win", "Loss", "Push"} and str(final_source or "").lower() in _FINAL_SOURCES:
            settled[name].add(str(market_key))

    rows = []
    for provider in providers:
        name = str(provider.get("name") or "")
        usage = provider.get("api_usage") or {}
        successes = int(usage.get("network_successes") or 0) + int(usage.get("not_modified") or 0)
        failures = int(usage.get("network_failures") or 0)
        total_attempts = successes + failures
        if name in _OFFER_SOURCES:
            eligible, verified_count = len(tracked[name]), len(settled[name])
            coverage = {
                "eligible": eligible, "verified": verified_count,
                "scope": "Tracked pregame prop markets past the 24-hour final-stat window, last 30 days",
            }
        elif provider.get("settlement_capable"):
            eligible, verified_count = attempted[name], verified[name]
            coverage = {
                "eligible": eligible, "verified": verified_count,
                "scope": "Latest recorded attempt per ledger leg and final-stat source, last 30 days",
            }
        else:
            eligible, verified_count = 0, 0
            coverage = {"eligible": 0, "verified": 0, "scope": "Context only; not a final-stat settlement source"}
        coverage["percent"] = _percentage(verified_count, eligible)
        rows.append({
            "name": name,
            "status": provider.get("status") or "unknown",
            "last_success_at": provider.get("last_success_at") or "",
            "age_minutes": provider.get("age_minutes"),
            "source_type": provider.get("source_type") or "unknown",
            "data_role": provider.get("data_role") or provider.get("purpose") or "Unclassified",
            "settlement_suitability": provider.get("settlement_suitability") or "Not for settlement",
            "officially_documented": bool(provider.get("officially_documented")),
            "network_attempts_this_session": total_attempts,
            "availability_percent_this_session": _percentage(successes, total_attempts),
            "error_percent_this_session": _percentage(failures, total_attempts),
            "settlement_coverage": coverage,
            "research_evidence": research[name],
        })
    return {
        "sources": rows, "truncated": truncated,
        "note": "Network rates cover only requests observed by this app process. Settlement coverage is scoped to tracked markets or latest recorded attempts for ledger legs, not every provider event. Research outcome links may repeat across entries and do not establish predictive accuracy.",
    }


def source_health_payload(health: dict) -> dict:
    now = utc_now()
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    since = now - timedelta(days=30)
    with SessionLocal() as session:
        facts = session.query(
            ResearchEvidenceModel.source_name,
            func.count(ResearchEvidenceModel.id),
            func.sum(ResearchEvidenceModel.use_count),
            func.sum(ResearchEvidenceModel.win_count + ResearchEvidenceModel.loss_count + ResearchEvidenceModel.push_count),
        ).filter(ResearchEvidenceModel.captured_at >= since).group_by(ResearchEvidenceModel.source_name).all()
        audits = session.query(
            SettlementAuditModel.provider, SettlementAuditModel.status, SettlementAuditModel.entry_prop_id,
        ).filter(SettlementAuditModel.attempted_at >= since).order_by(
            SettlementAuditModel.attempted_at, SettlementAuditModel.id,
        ).all()
        prediction_rows = session.query(
            PredictionRecordModel.platform, PredictionRecordModel.independent_market_key,
            PredictionRecordModel.game_time, PredictionRecordModel.outcome,
            PredictionRecordModel.outcome_source,
        ).filter(
            PredictionRecordModel.predicted_at >= since,
            PredictionRecordModel.legacy_quarantined.is_(False),
        ).order_by(PredictionRecordModel.predicted_at.desc()).limit(10001).all()
    return summarize_source_health(
        health.get("providers") or [], [tuple(row) for row in facts], [tuple(row) for row in audits],
        [tuple(row) for row in prediction_rows[:10000]],
        now=now, truncated=len(prediction_rows) > 10000,
    )
