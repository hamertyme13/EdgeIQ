from rich.console import Console

from models.entry import Entry

console = Console()


def display_entry(entry: Entry) -> None:
    """Display a player prop entry."""

    console.print("\n" + "=" * 40)
    console.print(f"Platform: {entry.platform}")
    console.print("=" * 40)

    for prop in entry.props:

        console.print()

        console.print(f"Player: {prop.player.name}")
        console.print(f"Team: {prop.player.team}")
        console.print(f"Sport: {prop.player.sport}")

        console.print(f"Stat: {prop.stat.value}")

        console.print(f"Line: {prop.line}")

        console.print(f"Projection: {prop.projection}")

        console.print(f"Edge: {prop.edge:+.1f}")

        console.print(f"Confidence: {prop.confidence:.0f}%")

        if prop.edge > 0:
            console.print("Recommendation: 🟢 OVER")

        elif prop.edge < 0:
            console.print("Recommendation: 🔴 UNDER")

        else:
            console.print("Recommendation: ⚪ PASS")
