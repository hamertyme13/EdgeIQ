from __future__ import annotations

import json
from datetime import UTC, datetime

from repository.database import SessionLocal
from repository.models.research_evidence_model import ResearchEvidenceModel
from repository.repositories.research_evidence_repository import ResearchEvidenceRepository


class TeamHistoryRepository:
    """Independent official game outcomes stored in the existing evidence ledger."""

    @staticmethod
    def save_outcomes(outcomes: list[dict]) -> int:
        facts = []
        for outcome in outcomes:
            if not outcome.get("game_id") or not outcome.get("game_start") or outcome.get("source") != "espn_official_scoreboard":
                continue
            for team in (outcome.get("home_team"), outcome.get("away_team")):
                if not team:
                    continue
                facts.append({
                    "player": team, "sport": outcome["sport"], "game": outcome["game"],
                    "evidence_type": "verified_team_game", "source_name": outcome["source"],
                    "source_url": f"https://www.espn.com/game/_/gameId/{outcome['game_id']}",
                    "ttl_minutes": 525600, "payload": outcome,
                })
        if facts:
            ResearchEvidenceRepository.record_many(facts)
        return len(facts)

    @staticmethod
    def before(sport: str, game_start: str) -> list[dict]:
        try:
            target = datetime.fromisoformat(game_start.replace("Z", "+00:00"))
            target = target.replace(tzinfo=UTC) if target.tzinfo is None else target.astimezone(UTC)
        except (ValueError, TypeError):
            return []
        cutoff = min(target, datetime.now(UTC)).replace(tzinfo=None)
        with SessionLocal() as session:
            evidence = session.query(ResearchEvidenceModel).filter_by(
                sport=sport.upper(), evidence_type="verified_team_game",
            ).filter(ResearchEvidenceModel.captured_at <= cutoff).order_by(
                ResearchEvidenceModel.captured_at.desc(),
            ).limit(3000).all()
            games = {}
            for record in evidence:
                outcome = json.loads(record.payload)
                started = datetime.fromisoformat(outcome["game_start"].replace("Z", "+00:00"))
                if started >= target:
                    continue
                key = str(outcome["game_id"])
                games.setdefault(key, outcome | {
                    "actual_home_points": outcome["home_points"], "actual_away_points": outcome["away_points"],
                    "actual_home_win": 1.0 if outcome["home_points"] > outcome["away_points"] else 0.0,
                    "captured_at": record.captured_at.isoformat(),
                })
            return list(games.values())
