def recommendation(prop) -> dict:

    if prop.edge >= 2:

        return {
            "grade": "A",
            "action": "Strong Consideration",
            "summary": "Projection is significantly above the line.",
            "color": "green",
        }

    elif prop.edge >= 1:

        return {
            "grade": "B",
            "action": "Consider",
            "summary": "Projection exceeds the line.",
            "color": "green",
        }

    elif prop.edge >= 0:

        return {
            "grade": "C",
            "action": "Lean Over",
            "summary": "Small positive edge.",
            "color": "yellow",
        }

    else:

        return {
            "grade": "F",
            "action": "Pass",
            "summary": "Projection is below the line.",
            "color": "red",
        }
