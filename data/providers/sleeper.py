"""Sleeper prop provider.

Sleeper does not expose a documented public Picks prop feed. Configure one of:
EDGEIQ_SLEEPER_PROPS_URL or EDGEIQ_SLEEPER_PROPS_FILE.
"""

from __future__ import annotations

from typing import Optional

from data.providers.generic_props import fetch_configured_props


def fetch_projections() -> list[dict]:
    return fetch_configured_props("Sleeper", "SLEEPER")


def top_props(n: int = 25, sport: Optional[str] = None) -> list[dict]:
    props = fetch_projections()
    if sport:
        props = [prop for prop in props if prop.get("league", "").upper() == sport.upper()]
    props.sort(key=lambda prop: prop.get("trending_count", 0), reverse=True)
    return props[:n]
