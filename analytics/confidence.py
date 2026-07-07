def confidence(edge: float) -> float:

    return min(
        max(
            50 + abs(edge) * 10,
            50,
        ),
        95,
    )