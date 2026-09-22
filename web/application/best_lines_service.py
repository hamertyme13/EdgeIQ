"""Compare thresholds without implying that different payouts are equivalent."""
from __future__ import annotations

import math
from datetime import UTC, datetime

from utils.entity_normalization import canonical_matchup_key


def best_lines_payload(payload: dict, direction: str = "Over") -> dict:
    direction = "Under" if direction.casefold() == "under" else "Over"
    rows = []
    groups: dict[tuple, list[dict]] = {}
    for prop in payload.get("lines") or []:
        try:
            line = float(prop.get("line"))
        except (ValueError, TypeError):
            continue
        if not math.isfinite(line):
            continue
        game = str(prop.get("game") or "")
        start = str(prop.get("game_time") or "")
        try:
            parsed = datetime.fromisoformat(start.replace("Z", "+00:00"))
            start = parsed.astimezone(UTC).isoformat() if parsed.tzinfo else ""
        except ValueError:
            start = ""
        offer = str(prop.get("line_offer_type") or "").lower()
        allowed = prop.get("allowed_directions") or ["Over", "Under"]
        if offer == "demon" or prop.get("is_premium_line"):
            allowed = ["Over"]
        eligible = (
            offer == "standard" and not prop.get("adjusted_line")
            and not prop.get("is_discounted_line") and not prop.get("is_premium_line")
            and direction.casefold() in {str(item).casefold() for item in allowed}
            and bool(game and start)
        )
        row = {
            **prop, "line": line, "comparison_direction": direction,
            "best_threshold": False, "comparable": eligible,
            "comparison_note": "Standard threshold; verify availability and complete-card payout."
            if eligible else "Not ranked: adjusted offer, restricted direction, or incomplete game identity.",
        }
        rows.append(row)
        if eligible:
            key = (str(prop.get("sport") or prop.get("league") or payload.get("sport")),
                   canonical_matchup_key(game), start, str(prop.get("stat") or payload.get("stat")))
            groups.setdefault(key, []).append(row)
    for group in groups.values():
        platforms = {row.get("platform") for row in group if row.get("platform")}
        if len(platforms) < 2:
            for row in group:
                row["comparison_note"] = "Only one provider for this exact game; no cross-provider comparison."
            continue
        best = (min if direction == "Over" else max)(row["line"] for row in group)
        for row in group:
            if row["line"] == best:
                row["best_threshold"] = True
                row["comparison_note"] = f"{'Lowest' if direction == 'Over' else 'Highest'} standard {direction} threshold for this game. Payouts may differ."
    return {
        "player": payload.get("player"), "stat": payload.get("stat"),
        "sport": payload.get("sport"), "direction": direction, "lines": rows,
        "available": bool(rows), "comparison_groups": len(groups),
        "message": "Provider snapshots, not confirmed live availability. EV is unverified without exact payout evidence.",
    }
