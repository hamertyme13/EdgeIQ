from rich.console import Console
from rich.table import Table

from models.prop import Prop

console = Console()


def review_prop(prop: Prop) -> bool:
    """Review the prop before analysis."""

    table = Table(
        title="Review Prop",
        show_header=False
    )

    table.add_column("Field", style="cyan")
    table.add_column("Value", style="white")

    table.add_row("Platform", prop.platform.value)
    table.add_row("Player", prop.player.name)
    table.add_row("Team", prop.player.team)
    table.add_row("Sport", prop.player.sport)
    table.add_row("Stat", prop.stat.value)
    table.add_row("Line", str(prop.line))
    table.add_row("Projection", str(prop.projection))

    console.print(table)

    while True:

        console.print()

        console.print("1. Generate Report")
        console.print("2. Cancel")

        choice = input("\nChoice: ").strip()

        if choice == "1":
            return True

        elif choice == "2":
            return False

        console.print("[red]Please choose 1 or 2.[/red]")