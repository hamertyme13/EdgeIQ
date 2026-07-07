from rich.console import Console
from rich.rule import Rule

console = Console()


def wizard_step(step: int, total: int, title: str) -> None:
    """Display a consistent wizard header."""

    console.print()

    console.print(
        Rule("[bold cyan]EdgeIQ Prop Builder[/bold cyan]")
    )

    console.print(
        f"[bold green]Step {step} of {total}[/bold green]"
    )

    console.print()

    console.print(
        f"[bold]{title}[/bold]"
    )

    console.print()