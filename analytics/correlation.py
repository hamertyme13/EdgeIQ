from models.entry import Entry
from utils.entity_normalization import canonical_matchup_key


def detect_correlations(entry: Entry) -> list[str]:
    """
    Analyze an entry for correlated props.

    Returns:
        list of warning strings.
    """

    warnings = []

    props = entry.props

    for i in range(len(props)):
        for j in range(i + 1, len(props)):

            first = props[i]
            second = props[j]

            if first.player.name == second.player.name:

                warnings.append(
                    f"{first.player.name} appears multiple times."
                )

            if first.player.team == second.player.team:

                warnings.append(
                    f"{first.player.team}: multiple teammates selected."
                )
            if first.stat == second.stat:

                warnings.append(
                    f"Multiple {first.stat.value} props."
                )

            if first.game and second.game and first.game == second.game:
                warnings.append(
                    f"{first.game}: same-game legs can share pace, blowout, and rotation risk."
                )

            first_stat = first.stat.value.lower()
            second_stat = second.stat.value.lower()

            if first.player.sport in {"NFL", "NCAAF"} and second.player.sport in {"NFL", "NCAAF"}:
                if _pair_contains(first_stat, second_stat, "passing yards", "receiving yards"):
                    warnings.append("QB passing yards and receiver yards are positively correlated.")
                if _pair_contains(first_stat, second_stat, "passing tds", "receiving tds"):
                    warnings.append("Passing TD and receiving TD legs are highly correlated.")
                if "rushing yards" in {first_stat, second_stat} and first.player.team == second.player.team:
                    warnings.append("Same-team rushing props can cannibalize volume.")

            if first.player.sport in {"NBA", "WNBA", "NCAAM", "NCAAW"} and first.player.team == second.player.team:
                if "rebounds" in first_stat and "rebounds" in second_stat:
                    warnings.append("Teammate rebound props can cannibalize each other.")
                if _pair_contains(first_stat, second_stat, "points", "assists"):
                    warnings.append("Same-team points and assists can depend on shared shot-making.")
                if "turnovers" in {first_stat, second_stat}:
                    warnings.append("Turnover props can be sensitive to pace and game script.")

            if first.player.sport == "MLB" and second.player.sport == "MLB":
                if _pair_contains(first_stat, second_stat, "pitcher strikeouts", "hits"):
                    warnings.append("Pitcher strikeouts and opposing hitter props can be inversely correlated.")
                if _pair_contains(first_stat, second_stat, "pitcher strikeouts", "total bases"):
                    warnings.append("Pitcher strikeouts and opposing total bases can be inversely correlated.")

    return list(dict.fromkeys(warnings))


def _pair_contains(first: str, second: str, left: str, right: str) -> bool:
    return (left in first and right in second) or (right in first and left in second)


def estimate_correlation_matrix(props: list) -> list[list[float]]:
    """Estimate conservative pairwise dependence for card-level EV simulation."""

    size = len(props)
    matrix = [[1.0 if row == column else 0.0 for column in range(size)] for row in range(size)]
    for left in range(size):
        for right in range(left + 1, size):
            correlation = _pair_correlation(props[left], props[right])
            matrix[left][right] = correlation
            matrix[right][left] = correlation
    return matrix


def _pair_correlation(first, second) -> float:
    first_game = canonical_matchup_key(_value(first, "game"))
    second_game = canonical_matchup_key(_value(second, "game"))
    same_game = bool(first_game and first_game == second_game)
    same_team = bool(_team(first) and _team(first) == _team(second))
    first_stat = _stat(first).lower()
    second_stat = _stat(second).lower()
    sport = _sport(first).upper()
    value = 0.0

    if same_game:
        value += 0.06
    if same_team:
        value += 0.04
    if sport in {"NBA", "WNBA", "NCAAM", "NCAAW"} and same_team:
        if _pair_contains(first_stat, second_stat, "points", "assists"):
            value += 0.10
        if "rebounds" in first_stat and "rebounds" in second_stat:
            value -= 0.14
    if sport in {"NFL", "NCAAF"} and same_team:
        if _pair_contains(first_stat, second_stat, "passing yards", "receiving yards"):
            value += 0.22
        if _pair_contains(first_stat, second_stat, "passing tds", "receiving tds"):
            value += 0.28
    if sport == "MLB" and same_game:
        if _pair_contains(first_stat, second_stat, "strikeouts", "hits"):
            value -= 0.20
        if _pair_contains(first_stat, second_stat, "strikeouts", "total bases"):
            value -= 0.18
    if _direction(first) != _direction(second):
        value *= -1
    return round(max(-0.30, min(0.30, value)), 3)


def _value(prop, name: str):
    return prop.get(name, "") if isinstance(prop, dict) else getattr(prop, name, "")


def _team(prop) -> str:
    if isinstance(prop, dict):
        return str(prop.get("team") or "")
    return str(getattr(getattr(prop, "player", None), "team", "") or "")


def _sport(prop) -> str:
    if isinstance(prop, dict):
        return str(prop.get("sport") or "")
    return str(getattr(getattr(prop, "player", None), "sport", "") or "")


def _stat(prop) -> str:
    value = _value(prop, "stat")
    return str(getattr(value, "value", value) or "")


def _direction(prop) -> str:
    return str(_value(prop, "direction") or "Over").lower()
