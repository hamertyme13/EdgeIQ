def recommendation(prop):

    if prop.edge >= 2:

        return (
            "A",
            "🔥 Strong Consideration",
            "Projection is significantly above the line.",
        )

    elif prop.edge >= 1:

        return (
            "B",
            "🟢 Consider",
            "Projection exceeds the line.",
        )

    elif prop.edge >= 0:

        return (
            "C",
            "🟡 Lean Over",
            "Small positive edge.",
        )

    else:

        return (
            "F",
            "🔴 Pass",
            "Projection is below the line.",
        )