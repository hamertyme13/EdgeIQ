"""Chalkboard prop provider.

Configure one of EDGEIQ_CHALKBOARD_PROPS_URL or EDGEIQ_CHALKBOARD_PROPS_FILE.
If an API requires auth, set EDGEIQ_CHALKBOARD_API_KEY.
"""

from __future__ import annotations

from typing import Optional

from data.providers.generic_props import fetch_configured_props


def fetch_projections() -> list[dict]:
    return fetch_configured_props("Chalkboard", "CHALKBOARD")


def top_props(n: int = 25, sport: Optional[str] = None) -> list[dict]:
    props = fetch_projections()
    if sport:
        props = [prop for prop in props if prop.get("league", "").upper() == sport.upper()]
    props.sort(key=lambda prop: prop.get("trending_count", 0), reverse=True)
    return props[:n]
