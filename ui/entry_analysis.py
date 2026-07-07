from rich.console import Console
from rich.panel import Panel
from analytics.risk import calculate_entry_risk
from models.entry import Entry

from analytics.entry_analysis import strongest_prop, weakest_prop
from analytics.entry_recommendation import recommendation
from analytics.correlation import detect_correlations

console = Console()

risk_icon = {
        "Low": "🟢",
        "Medium": "🟡",
        "High": "🔴",
    }

def display_entry_analysis(entry: Entry):

    best = strongest_prop(entry)
    worst = weakest_prop(entry)

    result = recommendation(entry)

    risk_result = calculate_entry_risk(entry.props)

    warnings = detect_correlations(entry)

    warning_text = ""

    if warnings:
        warning_text = "\n\n⚠ Correlation Warnings\n\n"

        for warning in warnings:
            warning_text += f"• {warning}\n"

    panel = Panel.fit(
        f"""
    🎯 Platform

    {entry.platform.value}

    📊 Number of Props

    {entry.prop_count}

    ⭐ Average Confidence

    {risk_result.average_confidence:.1f}%

    📈 Average Edge

    {risk_result.average_edge:+.2f}

    🛡 Entry Risk
    
    {risk_icon[risk_result.risk.value]} {risk_result.risk.value}

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

    {warning_text}
    """,
        title="EdgeIQ Entry Intelligence",
        border_style=result["color"],
    )

    console.print(panel)