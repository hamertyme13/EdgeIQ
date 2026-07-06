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

TOTAL_STEPS = 6


def choose_platform() -> Platform:

    wizard_step(1, TOTAL_STEPS, "Choose Platform")

    print("1. PrizePicks")
    print("2. Underdog")

    while True:

        choice = input("\nChoice: ").strip()

        if choice == "1":
            return Platform.PRIZEPICKS

        elif choice == "2":
            return Platform.UNDERDOG

        print("Please choose 1 or 2.")

def get_player_name() -> str:

    wizard_step(2, TOTAL_STEPS, "Player Name")

    while True:

        name = input("Player: ").strip()

        if name:
            return name

        print("Player name cannot be empty.")

def get_team() -> str:

    wizard_step(3, TOTAL_STEPS, "Team")

    while True:

        team = input("Team: ").strip()

        if team:
            return team

        print("Team cannot be empty.")

SPORTS = {
    "1": "NBA",
    "2": "WNBA",
    "3": "NFL",
    "4": "MLB"
}

def choose_sport() -> str:

    wizard_step(4, TOTAL_STEPS, "Choose Sport")

    print("1. NBA")
    print("2. WNBA")
    print("3. NFL")
    print("4. MLB")

    while True:

        choice = input("\nChoice: ").strip()

        if choice in SPORTS:
            return SPORTS[choice]

        print("Choose 1-4.")

STAT_OPTIONS = [
    StatType.POINTS,
    StatType.REBOUNDS,
    StatType.ASSISTS,
    StatType.PRA,
]

def choose_stat():

    wizard_step(
        5,
        TOTAL_STEPS,
        "Choose Stat"
    )

    for i, stat in enumerate(STAT_OPTIONS, start=1):

        print(f"{i}. {stat.value}")

    while True:

        try:

            choice = int(input("\nChoice: "))

            return STAT_OPTIONS[choice - 1]

        except (ValueError, IndexError):

            print("Invalid selection.")

def get_line_projection():

    wizard_step(
        6,
        TOTAL_STEPS,
        "Projection"
    )

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

            print("Enter valid numbers.")

def build_player() -> Player:

    name = get_player_name()

    team = get_team()

    sport = choose_sport()

    return Player(
        name=name,
        team=team,
        sport=sport,
    )

def build_prop(platform: Platform) -> Prop:

    player = build_player()

    platform = choose_platform()

    stat = choose_stat()

    line, projection = get_line_projection()

    edge = calculate_edge(line, projection)

    confidence  = calculate_confidence(edge)

    return Prop(
        player=player,
        stat=stat,
        line=line,
        projection=projection,
        edge=edge,
        confidence=confidence,
    )

    