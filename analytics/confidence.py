def confidence(edge: float) -> float:

    return min(
        max(
            50 + edge * 10,
            5,
        ),
        95,
    )
