"""Canonical sport/platform constants shared across the EdgeIQ codebase.

Import these instead of redefining them locally so that every module stays
in sync when new sports or platforms are added.
"""
from __future__ import annotations

SUPPORTED_SPORTS: tuple[str, ...] = (
    "WNBA",
    "NBA",
    "NFL",
    "MLB",
    "NHL",
    "NCAAF",
    "NCAAM",
    "NCAAW",
    "MLS",
    "EPL",
    "UCL",
    "TENNIS",
    "PGA",
    "MMA",
    "NASCAR",
    "CS2",
    "LOL",
    "VALORANT",
    "DOTA2",
    "COD",
    "APEX",
)

ESPORT_SPORTS: frozenset[str] = frozenset({"CS2", "LOL", "VALORANT", "DOTA2", "COD", "APEX"})

SPORT_ALIASES: dict[str, str | None] = {
    "ALL SPORTS": None,
    "WNBA": "WNBA",
    "NBA": "NBA",
    "NFL": "NFL",
    "MLB": "MLB",
    "NHL": "NHL",
    "HOCKEY": "NHL",
    "COLLEGE FOOTBALL": "NCAAF",
    "NCAAF": "NCAAF",
    "CFB": "NCAAF",
    "COLLEGE BASKETBALL": "NCAAM",
    "NCAAM": "NCAAM",
    "CBB": "NCAAM",
    "NCAAW": "NCAAW",
    "WOMENS COLLEGE BASKETBALL": "NCAAW",
    "WOMEN'S COLLEGE BASKETBALL": "NCAAW",
    "MLS": "MLS",
    "EPL": "EPL",
    "PREMIER LEAGUE": "EPL",
    "UCL": "UCL",
    "CHAMPIONS LEAGUE": "UCL",
    "SOCCER": "MLS",
    "TENNIS": "TENNIS",
    "ATP": "TENNIS",
    "WTA": "TENNIS",
    "PGA": "PGA",
    "GOLF": "PGA",
    "MMA": "MMA",
    "UFC": "MMA",
    "NASCAR": "NASCAR",
    "CS": "CS2",
    "CS2": "CS2",
    "COUNTER STRIKE": "CS2",
    "COUNTER-STRIKE": "CS2",
    "LOL": "LOL",
    "LEAGUE OF LEGENDS": "LOL",
    "VAL": "VALORANT",
    "VALORANT": "VALORANT",
    "DOTA": "DOTA2",
    "DOTA2": "DOTA2",
    "DOTA 2": "DOTA2",
    "COD": "COD",
    "CALL OF DUTY": "COD",
    "APEX": "APEX",
    "APEX LEGENDS": "APEX",
}


def canonical_sport(value: object, default: str | None = None) -> str | None:
    """Normalize user/provider sport text to an EdgeIQ sport code."""
    text = " ".join(str(value or "").strip().upper().split())
    if not text:
        return default
    return SPORT_ALIASES.get(text, text if text in SUPPORTED_SPORTS else default)


def sport_filter(value: object) -> str | None:
    """Normalize an API sport filter; All Sports becomes ``None``."""
    return canonical_sport(value)
