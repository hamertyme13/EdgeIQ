"""Canonical sportsbook and pick'em platform configuration."""
from __future__ import annotations

ENTRY_PLATFORMS: tuple[str, ...] = ("PrizePicks", "Underdog", "DraftKings Pick6", "Sleeper")
# "Both" scans remain limited to providers that do not consume a metered actor
# run. DraftKings Pick6 is available when selected explicitly.
GENERATOR_PLATFORMS: tuple[str, ...] = ("PrizePicks", "Underdog", "Sleeper")
CONTEXT_PLATFORMS: tuple[str, ...] = ("Ball Don't Lie",)
PROP_PLATFORMS: tuple[str, ...] = (*ENTRY_PLATFORMS, *CONTEXT_PLATFORMS)
PLATFORM_FILTERS: tuple[str, ...] = (*PROP_PLATFORMS, "Both")

PLATFORM_ALIASES: dict[str, str] = {
    "prizepicks": "PrizePicks",
    "prize picks": "PrizePicks",
    "underdog": "Underdog",
    "underdog fantasy": "Underdog",
    "draftkings": "DraftKings Pick6",
    "draft kings": "DraftKings Pick6",
    "draftkings pick6": "DraftKings Pick6",
    "dk pick6": "DraftKings Pick6",
    "pick6": "DraftKings Pick6",
    "sleeper": "Sleeper",
    "ball don't lie": "Ball Don't Lie",
    "balldontlie": "Ball Don't Lie",
    "both": "Both",
    "all": "Both",
    "all platforms": "Both",
}

PLATFORM_MAX_LEGS: dict[str, int] = {
    "PrizePicks": 6,
    "Underdog": 8,
    "DraftKings Pick6": 6,
    "Sleeper": 5,
}


def canonical_platform(value: object, default: str = "") -> str:
    """Return EdgeIQ's display name for a provider alias."""
    text = str(value or "").strip()
    return PLATFORM_ALIASES.get(text.casefold(), text or default)


def maximum_entry_legs(platform: object) -> int:
    """Return the supported card size for a canonical or aliased platform."""
    return PLATFORM_MAX_LEGS.get(canonical_platform(platform), 5)
