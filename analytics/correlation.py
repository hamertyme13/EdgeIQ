from models.entry import Entry


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
