from __future__ import annotations

from functools import lru_cache

from models.stat_type import StatType

_STAT_ALIASES: dict[StatType, tuple[str, ...]] = {
    StatType.GAME_WINNER: ("winner", "moneyline", "game outcome", "match winner", "team to win"),
    StatType.PRA: (
        "pra",
        "p+r+a",
        "pts+rebs+asts",
        "pts rebs asts",
        "points rebounds assists",
        "points + rebounds + assists",
    ),
    StatType.STEALS_BLOCKS: ("stls+blks", "stls blks", "blocks + steals", "blocks steals"),
    StatType.DOUBLE_DOUBLES: ("double double", "double-double"),
    StatType.TRIPLE_DOUBLES: ("triple double", "triple-double"),
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
    StatType.FIELD_GOALS_ATTEMPTED: ("fg attempted", "fg attempts", "fga", "field goal attempts"),
    StatType.FIELD_GOALS_MADE: ("fg made", "fgm", "field goals"),
    StatType.FREE_THROWS_ATTEMPTED: ("ft attempted", "ft attempts", "fta", "free throw attempts"),
    StatType.FREE_THROWS_MADE: ("ft made", "ftm", "free throws"),
    StatType.THREES_ATTEMPTED: ("3pt attempted", "3pt attempts", "3pa", "three pointers attempted"),
    StatType.THREES: ("3pt made", "3pm", "three pointers made"),
    StatType.TWO_POINTERS_ATTEMPTED: ("2pt attempted", "2pt attempts", "2pa"),
    StatType.TWO_POINTERS_MADE: ("2pt made", "2pm"),
    StatType.OFFENSIVE_REBOUNDS: ("oreb", "off rebounds"),
    StatType.DEFENSIVE_REBOUNDS: ("dreb", "def rebounds"),
    StatType.PASS_RUSH_YARDS: ("pass+rush yards", "passing + rushing yards", "passing rushing yards"),
    StatType.PASS_RUSH_TDS: ("pass+rush tds", "passing + rushing touchdowns", "passing rushing touchdowns"),
    StatType.SOLO_TACKLES: ("solo", "solo tackles"),
    StatType.ASSISTED_TACKLES: ("tackle assists", "assisted tackles"),
    StatType.TACKLES: (
        "tackles + assists",
        "tackles assists",
        "total tackles",
        "combined tackles",
    ),
    StatType.EXTRA_POINTS_MADE: ("xp made", "xpm", "extra points made", "pat made", "pats made"),
    StatType.EXTRA_POINTS_ATTEMPTED: ("xp attempted", "xpa", "extra points attempted", "pat attempts"),
    StatType.FIELD_GOALS_KICKING_MADE: ("kicking fg made", "field goals kicking made"),
    StatType.FIELD_GOALS_KICKING_ATTEMPTED: ("kicking fg attempted", "field goals kicking attempted"),
    StatType.LONGEST_FIELD_GOAL: ("longest fg", "fg long"),
    StatType.FANTASY_SCORE: ("fantasy points", "fantasy pts", "fantasy score"),
    StatType.OUTS_RECORDED: ("pitching outs", "outs", "outs recorded"),
    StatType.PITCHING_WALKS: ("walks allowed", "pitcher walks", "pitching walks"),
    StatType.HITS_ALLOWED: ("hits allowed", "pitcher hits allowed"),
    StatType.STOLEN_BASES: ("stolen base", "stolen bases", "sb"),
    StatType.HIT_BY_PITCH: ("hit by pitch", "hbp"),
    StatType.BATTERS_FACED: ("batters faced", "bf"),
    StatType.PITCHES: ("pitch count", "pitches thrown", "pitches"),
    StatType.AT_BATS: ("at bat", "at bats", "ab"),
    StatType.PLATE_APPEARANCES: ("plate appearance", "plate appearances", "pa"),
    StatType.TOTAL_BASES: ("total base", "total bases", "tb"),
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
    return _matched_stat_type_text(str(value or ""))


@lru_cache(maxsize=1024)
def _matched_stat_type_text(raw_value: str) -> StatType | None:
    text = _stat_text(raw_value)
    if not text:
        return None

    for stat in StatType:
        if text == _stat_text(stat.value):
            return stat

    for alias_text, stat in _alias_candidates():
        if _alias_matches(text, alias_text):
            return stat

    if "+" in raw_value:
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


@lru_cache(maxsize=1)
def _alias_candidates() -> tuple[tuple[str, StatType], ...]:
    return tuple(sorted(
        (
            (_stat_text(alias), stat)
            for stat, aliases in _STAT_ALIASES.items()
            for alias in aliases
        ),
        key=lambda candidate: len(candidate[0]),
        reverse=True,
    ))


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
