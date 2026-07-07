def recommendation(ev_percent: float) -> dict:

    if ev_percent >= 15:
        return {
            "grade": "A+",
            "action": "🔥 Consider This Bet",
            "summary": "Excellent betting value.",
            "color": "bold green",
        }

    elif ev_percent >= 10:
        return {
            "grade": "A",
            "action": "🟢 Consider This Bet",
            "summary": "Strong positive expected value.",
            "color": "green",
        }

    elif ev_percent >= 5:
        return {
            "grade": "B",
            "action": "🟡 Worth Considering",
            "summary": "Positive value, but not elite.",
            "color": "yellow",
        }

    elif ev_percent >= 0:
        return {
            "grade": "C",
            "action": "⚪ Small Edge",
            "summary": "Marginal value. Shop for better odds.",
            "color": "cyan",
        }

    else:
        return {
            "grade": "F",
            "action": "🔴 Pass",
            "summary": "Negative expected value.",
            "color": "red",
        }
    