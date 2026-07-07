from rich.console import Console
from rich.table import Table

from models.entry import Entry

console = Console()


def review_entry(entry: Entry) -> bool:

    table = Table(title="Review Entry")

    table.add_column("#")
    table.add_column("Player")
    table.add_column("Stat")
    table.add_column("Line")

    for i, prop in enumerate(entry.props, start=1):

        table.add_row(
            str(i),
            prop.player.name,
            prop.stat.value,
            str(prop.line),
        )

    console.print(table)

    while True:

        choice = input(
            "\nGenerate Entry Report? (y/n): "
        ).strip().lower()

        if choice == "y":
            return True

        if choice == "n":
            return False