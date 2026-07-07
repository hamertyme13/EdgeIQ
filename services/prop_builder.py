from rich.console import Console

from models.platform import Platform

from ui.wizard import wizard_step

from models.stat_type import StatType

from models.player import Player

from models.prop import Prop

from analytics.confidence import confidence

from analytics.prop_metrics import (
    calculate_edge,
    calculate_confidence,
)
from utils.display import divider

console = Console()

TOTAL_STEPS = 6


def choose_platform() -> Platform:

    wizard_step(1, TOTAL_STEPS, "Choose Platform")

    console.print("1. PrizePicks")
    console.print("2. Underdog")

    while True:

        choice = input("\nChoice: ").strip()

        if choice == "1":
            return Platform.PRIZEPICKS

        elif choice == "2":
            return Platform.UNDERDOG

        console.print("[red]Please choose 1 or 2.[/red]")

def get_player_name() -> str:

    console.print("Player Name\n")

    while True:

        name = input("Player: ").strip()

        if name:
            return name

        console.print("[red]Player name cannot be empty.[/red]")

def get_team() -> str:

    console.print("Team\n")

    while True:

        team = input("Team: ").strip()

        if team:
            return team

        console.print("[red]Team cannot be empty.[/red]")

SPORTS = {
    "1": "NBA",
    "2": "WNBA",
    "3": "NFL",
    "4": "MLB"
}

def choose_sport() -> str:

    console.print("Choose Sport\n")

    console.print("1. NBA")
    console.print("2. WNBA")
    console.print("3. NFL")
    console.print("4. MLB")

    while True:

        choice = input("\nChoice: ").strip()

        if choice in SPORTS:
            return SPORTS[choice]

        console.print("[red]Choose 1-4.[/red]")

STAT_OPTIONS = [
    StatType.POINTS,
    StatType.REBOUNDS,
    StatType.ASSISTS,
    StatType.PRA,
]

def choose_stat():

    console.print("Choose Stat\n")

    for i, stat in enumerate(STAT_OPTIONS, start=1):

        console.print(f"{i}. {stat.value}")

    while True:

        try:

            choice = int(input("\nChoice: "))

            return STAT_OPTIONS[choice - 1]

        except (ValueError, IndexError):

            console.print("[red]Invalid selection.[/red]")

def get_line_projection():

    while True:

        try:

            line = float(
                input("Posted Line: ")
            )

            projection = float(
                input("Your Projection: ")
            )

            return line, projection

        except ValueError:

            console.print("[red]Enter valid numbers.[/red]")

def build_player() -> Player:

    name = get_player_name()

    team = get_team()

    sport = choose_sport()

    return Player(
        name=name,
        team=team,
        sport=sport,
    )

def build_prop(platform: Platform, prop_number: int = 1) -> Prop:

    divider(f"Building Prop #{prop_number}")

    wizard_step(1,
                5,
                "Player"
                )
    player = build_player()

    wizard_step(2,
                5,
                "Stat"
                )

    stat = choose_stat()

    wizard_step(3,
                5,
                "Projection"
                )

    line, projection = get_line_projection()

    wizard_step(4,
                5,
                "Edge Analysis"
                )

    edge = calculate_edge(line, projection)

    wizard_step(5,
                5,
                "Confidence"
                )

    confidence = calculate_confidence(edge)

    return Prop(
        player=player,
        stat=stat,
        line=line,
        projection=projection,
        edge=edge,
        confidence=confidence,
        platform=platform,
    )
