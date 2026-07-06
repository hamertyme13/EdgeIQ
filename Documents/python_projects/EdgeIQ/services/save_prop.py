from rich.console import Console

console = Console()


def save_prop(prop) -> None:
    """
    Temporary save workflow.
    Will use PropRepository in Sprint 2.2.
    """

    console.print()

    console.print(
        "[green]✓ Prop saved successfully![/green]"
    )

    console.print(
        "[dim]SQLite persistence coming in Sprint 2.2[/dim]"
    )