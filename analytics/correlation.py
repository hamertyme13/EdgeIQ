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

    return list(dict.fromkeys(warnings))
