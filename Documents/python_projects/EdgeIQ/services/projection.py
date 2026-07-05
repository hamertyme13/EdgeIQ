def edge(line: float, projection: float) -> float:
    """
    Returns the numerical edge between the sportsbook line
    and the user's projection.
    """
    return projection - line

def confidence(edge: float) -> float:
    """
    Converts the edge into a simple confidence score.
    """

    score = abs(edge) * 20

    return min(score, 100)