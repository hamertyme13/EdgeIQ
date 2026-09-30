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


def attach_offer_snapshots(payload: dict, updated_sections: set[str], capture) -> None:
    """Link only newly generated recommendations to immutable provider terms."""
    candidates: list[dict] = []

    def visit(value: object) -> None:
        if isinstance(value, dict):
            if value.get("player") and value.get("stat") and value.get("line") is not None and value.get("platform"):
                candidates.append(value)
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    for section in updated_sections:
        visit(payload.get(section))
    if not candidates:
        return
    for original, stamped in zip(candidates, capture(candidates), strict=True):
        original["offer_snapshot_id"] = stamped.get("offer_snapshot_id") or ""


def attach_leg_recommendations(payload: dict, updated_sections: set[str], capture) -> None:
    """Capture only newly supplied recommendations, never relabel retained feed rows."""
    candidates: list[dict] = []

    def visit(value: object) -> None:
        if isinstance(value, dict):
            if value.get("offer_snapshot_id") and value.get("player") and value.get("stat"):
                candidates.append(value)
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    for section in updated_sections:
        visit(payload.get(section))
    capture(candidates)
