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
    StatType.PASSING_YARDS: ("pass yards", "passing yds", "pass yds"),
    StatType.PASSING_TDS: ("pass tds", "pass touchdowns", "passing touchdowns"),
    StatType.PASSING_ATTEMPTS: ("pass attempts", "passing attempts"),
    StatType.COMPLETIONS: ("pass completions", "passing completions"),
    StatType.INTERCEPTIONS: ("int", "ints", "ints thrown", "interceptions thrown"),
    StatType.RUSHING_YARDS: ("rush yards", "rushing yds", "rush yds"),
    StatType.RUSH_ATTEMPTS: ("carries", "rush attempts", "rushing attempts"),
    StatType.RUSHING_TDS: ("rush tds", "rushing touchdowns"),
    StatType.RECEIVING_YARDS: ("rec yards", "receiving yds", "rec yds"),
    StatType.RECEPTIONS: ("recs",),
    StatType.RECEIVING_TDS: ("rec tds", "receiving touchdowns"),
    StatType.RUSH_RECEIVING_YARDS: (
        "rush+rec yards",
        "rush rec yards",
        "rushing + receiving yards",
        "rushing receiving yards",
    ),
    StatType.RUSH_RECEIVING_TDS: (
        "rush+rec tds",
        "rush rec tds",
        "rushing + receiving touchdowns",
        "rushing receiving touchdowns",
    ),
    StatType.SACKS: ("defensive sacks",),
    StatType.TACKLES: (
        "tackles + assists",
        "tackles assists",
        "total tackles",
        "combined tackles",
    ),
    StatType.EXTRA_POINTS_MADE: ("xp made", "extra points made"),
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

    alias_candidates = sorted(
        (
            (_stat_text(alias), stat)
            for stat, aliases in _STAT_ALIASES.items()
            for alias in aliases
        ),
        key=lambda candidate: len(candidate[0]),
        reverse=True,
    )
    for alias_text, stat in alias_candidates:
        if _alias_matches(text, alias_text):
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


def _alias_matches(text: str, alias: str) -> bool:
    alias_text = _stat_text(alias)
    if len(alias_text) <= 4:
        return text == alias_text
    return alias_text in text


def _stat_text(value: object) -> str:
    return (
        str(value or "")
        .strip()
        .lower()
        .replace("-", " ")
        .replace("_", " ")
        .replace(" + ", "+")
    )
