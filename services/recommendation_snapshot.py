from __future__ import annotations

from datetime import datetime

from analytics.opportunity_score import locked_opportunity_score


def stamp_snapshot_payload(payload: dict, snapshot_id: str, model_version: str,
                           captured_at: datetime, *, updated_sections: set[str]) -> None:
    """Stamp only newly supplied sections, never relabel retained historical feeds."""
    payload["snapshot_id"] = snapshot_id
    payload["model_version"] = model_version

    def stamp_rows(rows: list) -> None:
        for row in rows:
            if not isinstance(row, dict):
                continue
            row["recommendation_snapshot_id"] = snapshot_id
            row["model_version"] = model_version
            if row.get("player") and row.get("stat") and row.get("line") is not None:
                row["edgeiq_score"] = locked_opportunity_score(row, snapshot_id, captured_at)
            stamp_rows(row.get("props") or [])

    for key in updated_sections:
        if key == "props":
            stamp_rows(payload.get(key) or [])
        elif key in {"daily_briefing", "opportunity_feed"}:
            section = payload.get(key)
            if not isinstance(section, dict):
                continue
            section["recommendation_snapshot_id"] = snapshot_id
            section["model_version"] = model_version
            for field in ("opportunities", "top_opportunities", "suggested_entries"):
                stamp_rows(section.get(field) or [])
            for rows in (section.get("sections") or {}).values():
                stamp_rows(rows)
