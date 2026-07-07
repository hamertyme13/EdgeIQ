from rich.console import Console
from rich.panel import Panel

from models.prop import Prop
from analytics.recommendation import recommendation

console = Console()


def display_prop_analysis(prop: Prop) -> None:

    result = recommendation(prop)

    panel = Panel.fit(
        f"""
🏀 Player
{prop.player.name}

🎯 Platform
{prop.platform.value}

📈 Stat
{prop.stat.value}

📏 Line
{prop.line}

📊 Projection
{prop.projection}

📈 Betting Edge
{prop.edge:+.1f}

⭐ Confidence
{prop.confidence:.0f}%

Recommendation

{result.action}
""",
        title="EdgeIQ Prop Analysis",
        border_style="cyan",
    )

    console.print(panel)