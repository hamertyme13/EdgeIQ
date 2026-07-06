from analytics.confidence import confidence


def calculate_edge(
    line: float,
    projection: float
) -> float:
    """Calculate the betting edge."""

    return projection - line


def calculate_confidence(
    edge: float
) -> float:
    """Calculate confidence from the edge."""

    return confidence(edge)