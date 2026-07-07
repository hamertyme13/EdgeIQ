from models.entry import Entry


def display_entry(entry: Entry) -> None:
    """Display a player prop entry."""

    print("\n" + "=" * 40)
    print(f"Platform: {entry.platform}")
    print("=" * 40)

    for prop in entry.props:

        print()

        print(f"Player: {prop.player.name}")
        print(f"Team: {prop.player.team}")
        print(f"Sport: {prop.player.sport}")

        print(f"Stat: {prop.stat.value}")

        print(f"Line: {prop.line}")

        print(f"Projection: {prop.projection}")

        print(f"Edge: {prop.edge:+.1f}")

        print(f"Confidence: {prop.confidence:.0f}%")

        if prop.edge > 0:
            print("Recommendation: 🟢 OVER")

        elif prop.edge < 0:
            print("Recommendation: 🔴 UNDER")

        else:
            print("Recommendation: ⚪ PASS")