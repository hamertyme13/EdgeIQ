from config import APP_NAME, APP_SUBTITLE, APP_VERSION
from rich.console import Console
from rich.panel import Panel

console = Console()


def title() -> None:
    console.print(
        Panel.fit(
            f"[bold cyan]{APP_NAME}[/bold cyan]\n"
            f"{APP_SUBTITLE}\n"
            f"[dim]{APP_VERSION}[/dim]",
            border_style="cyan",
        )
    )


def divider(title="EdgeIQ Prop Builder"):
    console.rule(f"[cyan]{title}[/cyan]")