from rich.console import Console
from rich.panel import Panel

from models.entry import Entry

from analytics.entry_analysis import strongest_prop, weakest_prop
from analytics.entry_recommendation import recommendation

console = Console()


def display_entry_analysis(entry: Entry):

    best = strongest_prop(entry)
    worst = weakest_prop(entry)

    result = recommendation(entry)

    panel = Panel.fit(
        f"""
    🎯 Platform

    {entry.platform.value}

    📊 Number of Props

    {entry.prop_count}

    ⭐ Average Confidence

    {entry.average_confidence:.1f}%

    📈 Average Edge

    {entry.average_edge:+.2f}

    🔥 Strongest Prop

    {best.player.name}

    {best.stat.value}

    Edge: {best.edge:+.2f}

    ❄️ Weakest Prop

    {worst.player.name}

    {worst.stat.value}

    Edge: {worst.edge:+.2f}

    🏆 Overall Grade

    {result["grade"]}

    🔍 Recommendation

    {result["action"]}

    Reason

    {result["reason"]}
    """,
        title="EdgeIQ Entry Intelligence",
        border_style=result["color"],
    )

    console.print(panel)