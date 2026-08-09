from __future__ import annotations

import json
from datetime import UTC, datetime

from analytics.prediction_evidence import independent_market_key
from repository.repositories.settings_repository import SettingsRepository


class ModelRehabilitationRepository:
    FEED_KEY = "canonical_recommendation_snapshot"
    SHADOW_KEY = "shadow_prediction_registry"

    @staticmethod
    def save_feed(payload: dict) -> None:
        current = ModelRehabilitationRepository.load_feed()
        merged = {**current, **payload}
        SettingsRepository.set(ModelRehabilitationRepository.FEED_KEY, json.dumps(merged, default=str))

    @staticmethod
    def load_feed() -> dict:
        return _json(SettingsRepository.get(ModelRehabilitationRepository.FEED_KEY, ""), {})

    @staticmethod
    def queue_shadow(rows: list[dict], *, model_version: str, target: int = 227) -> dict:
        registry = _json(SettingsRepository.get(ModelRehabilitationRepository.SHADOW_KEY, ""), [])
        existing = {str(row.get("independent_market_key") or "") for row in registry}
        needed = max(0, target - len(registry))
        created = 0
        now = datetime.now(UTC).isoformat()
        for row in rows:
            key = independent_market_key(row)
            if not key or key in existing:
                continue
            registry.append({
                "independent_market_key": key,
                "model_version": model_version,
                "player": row.get("player", ""),
                "sport": row.get("sport") or row.get("league") or "",
                "stat": row.get("stat", ""),
                "line": row.get("line"),
                "direction": row.get("direction", "Over"),
                "probability": row.get("confidence"),
                "platform": row.get("platform", ""),
                "game": row.get("game", ""),
                "game_time": row.get("game_time", ""),
                "predicted_at": now,
                "status": "shadow_pending",
            })
            existing.add(key)
            created += 1
            if created >= needed:
                break
        SettingsRepository.set(ModelRehabilitationRepository.SHADOW_KEY, json.dumps(registry, default=str))
        return {
            "created": created,
            "queued": len(registry),
            "remaining_target": max(0, target - len(registry)),
            "message": "Shadow predictions do not count as evidence until verified final outcomes arrive.",
        }

    @staticmethod
    def reconcile_shadow(evidence_rows: list[dict]) -> int:
        registry = _json(SettingsRepository.get(ModelRehabilitationRepository.SHADOW_KEY, ""), [])
        outcomes = {
            str(row.get("independent_market_key") or ""): row
            for row in evidence_rows
            if row.get("result") in {"Win", "Loss", "Push"}
            and str(row.get("outcome_source") or "").strip().lower()
            not in {"", "unknown", "unmatched", "projection_estimate", "integrity_quarantine"}
        }
        updated = 0
        for row in registry:
            outcome = outcomes.get(str(row.get("independent_market_key") or ""))
            if not outcome or row.get("status") in {"Win", "Loss", "Push"}:
                continue
            row["status"] = outcome["result"]
            row["actual"] = outcome.get("actual")
            row["outcome_source"] = outcome.get("outcome_source")
            row["settled_at"] = str(outcome.get("settled_at") or "")
            updated += 1
        if updated:
            SettingsRepository.set(ModelRehabilitationRepository.SHADOW_KEY, json.dumps(registry, default=str))
        return updated

    @staticmethod
    def shadow_status(evidence_rows: list[dict] | None = None) -> dict:
        if evidence_rows is not None:
            ModelRehabilitationRepository.reconcile_shadow(evidence_rows)
        registry = _json(SettingsRepository.get(ModelRehabilitationRepository.SHADOW_KEY, ""), [])
        settled = [row for row in registry if row.get("status") in {"Win", "Loss", "Push"}]
        decisions = [row for row in settled if row.get("status") in {"Win", "Loss"}]
        wins = sum(row.get("status") == "Win" for row in decisions)
        return {
            "queued": len(registry),
            "settled": len(settled),
            "accuracy": round(wins / len(decisions) * 100.0, 1) if decisions else 0.0,
            "release_ready": len(decisions) >= 100 and wins / len(decisions) >= 0.55,
            "mode": "shadow" if len(decisions) < 100 else "review",
            "release_requirements": {
                "minimum_settled": 100,
                "minimum_accuracy": 55.0,
                "requires_verified_outcomes": True,
            },
        }


def _json(value: str, default):
    try:
        parsed = json.loads(value or "")
        return parsed if isinstance(parsed, type(default)) else default
    except (TypeError, ValueError):
        return default
