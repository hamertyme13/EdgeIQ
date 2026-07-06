from models.entry import Entry


def recommendation(entry: Entry) -> dict:

    confidence = entry.average_confidence

    if confidence >= 75:

        return {
            "grade": "A",
            "action": "🟢 Submit Entry",
            "reason": "Excellent overall confidence.",
            "color": "green",
        }

    elif confidence >= 65:

        return {
            "grade": "B",
            "action": "🟡 Worth Considering",
            "reason": "Solid confidence across the entry.",
            "color": "yellow",
        }

    elif confidence >= 55:

        return {
            "grade": "C",
            "action": "⚪ Borderline",
            "reason": "Some props may need review.",
            "color": "cyan",
        }

    return {
        "grade": "F",
        "action": "🔴 Pass",
        "reason": "Entry confidence is too low.",
        "color": "red",
    }