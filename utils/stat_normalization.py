from __future__ import annotations

from models.stat_type import StatType


_STAT_ALIASES: dict[StatType, tuple[str, ...]] = {
    StatType.PRA: (
        "pra",
        "p+r+a",
        "pts+rebs+asts",
        "pts rebs asts",
        "points rebounds assists",
        "points + rebounds + assists",
    ),
    StatType.POINTS_REBOUNDS: (
        "pr",
        "p+r",
        "pts+rebs",
        "points rebounds",
        "points + rebounds",
    ),
    StatType.POINTS_ASSISTS: (
        "pa",
        "p+a",
        "pts+asts",
        "points assists",
        "points + assists",
    ),
    StatType.REBOUNDS_ASSISTS: (
        "ra",
        "r+a",
        "rebs+asts",
        "rebounds assists",
        "rebounds + assists",
    ),
    StatType.HITS_RUNS_RBIS: (
        "h+r+rbi",
        "hits+runs+rbis",
        "hit run rbi",
        "hits runs rbis",
        "hits + runs + rbis",
    ),
}


def stat_type_from_text(value: object, default: StatType = StatType.POINTS) -> StatType:
    return _matched_stat_type(value) or default


def canonical_stat_label(value: object) -> str:
    stat = _matched_stat_type(value)
    return stat.value if stat else str(value or "").strip()


def stat_alias_labels(value: object) -> list[str]:
    stat = _matched_stat_type(value)
    if stat is None:
        label = str(value or "").strip()
        return [label] if label else []

    labels = {stat.value}
    labels.update(alias.upper() if alias in {"pra"} else alias for alias in _STAT_ALIASES.get(stat, ()))
    labels.update(alias.title() for alias in _STAT_ALIASES.get(stat, ()))
    return sorted(labels)


def stat_key(value: object) -> str:
    return _stat_text(canonical_stat_label(value))


def _matched_stat_type(value: object) -> StatType | None:
    text = _stat_text(value)
    if not text:
        return None

    for stat, aliases in _STAT_ALIASES.items():
        if any(alias in text for alias in aliases):
            return stat

    if "+" in str(value or ""):
        return None

    if "pitcher" in text and ("strikeout" in text or text == "ks"):
        return StatType.PITCHER_STRIKEOUTS
    if "strikeout" in text or text in {"ks", "k"}:
        return StatType.STRIKEOUTS
    if "passing" in text and "yard" in text:
        return StatType.PASSING_YARDS
    if "rushing" in text and "yard" in text:
        return StatType.RUSHING_YARDS
    if "receiving" in text and "yard" in text:
        return StatType.RECEIVING_YARDS
    if "reception" in text:
        return StatType.RECEPTIONS
    if "shot" in text and "goal" in text:
        return StatType.SHOTS_ON_GOAL
    if "shot" in text and "target" in text:
        return StatType.SHOTS_ON_TARGET
    if "home run" in text or text == "hr":
        return StatType.HOME_RUNS
    if "total base" in text:
        return StatType.TOTAL_BASES
    if "rbi" in text:
        return StatType.RBIS

    for stat in sorted(StatType, key=lambda candidate: len(candidate.value), reverse=True):
        stat_text = _stat_text(stat.value)
        if stat_text == text or stat_text in text:
            return stat

    if "hit" in text:
        return StatType.HITS
    if "point" in text or text in {"pts", "pt"}:
        return StatType.POINTS
    if "rebound" in text or "reb" in text:
        return StatType.REBOUNDS
    if "assist" in text or "ast" in text:
        return StatType.ASSISTS
    return None


def _stat_text(value: object) -> str:
    return (
        str(value or "")
        .strip()
        .lower()
        .replace("-", " ")
        .replace("_", " ")
    )
