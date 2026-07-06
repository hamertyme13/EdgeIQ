from rich.console import Console

console = Console()

CONFIDENCE_MAP = {
    1: 45.0,
    2: 52.0,
    3: 57.0,
    4: 63.0,
    5: 70.0,
}

CONFIDENCE_LABELS = {
    1: "Proceed with caution",
    2: "Slight lean",
    3: "Playable",
    4: "Strong play",
    5: "Premium play",
}


def quick_probability() -> float:
    """Estimate probability using a simple confidence scale."""

    print("\nHow confident are you that this prop will hit?\n")

    console.print("[green]★★★★★ Premium Play[/green]")
    console.print("[yellow]★★★★ Strong Play[/yellow]")
    console.print("[cyan]★★★ Playable[/cyan]")
    console.print("[magenta]★★ Slight Lean[/magenta]")
    console.print("[red]★ Proceed with Caution[/red]")

    console.print("\nTip: These percentages are estimates that EdgeIQ uses")
    console.print("to calculate Expected Value (EV).")

    while True:

        try:

            choice = int(input("\nChoice: "))

            if choice in CONFIDENCE_MAP:
                probability = CONFIDENCE_MAP[choice]
                label = CONFIDENCE_LABELS[choice]
                print(f"\n✓ Your estimated probability is {probability:.1f}%")
                print(f"✓ Confidence Level: {label}\n")
                print("EdgeIQ uses this probability to calculate Expected Value (EV) for your bet.")
                return probability

            print("Choose a number between 1 and 5.")

        except ValueError:

            print("Please enter a valid number.")

def advanced_probability() -> float:

    while True:

        try:

            probability = float(
                input("\nProjected Win Probability (%): ")
            )

            if 0 <= probability <= 100:
                return probability

            print("Enter a value between 0 and 100.")

        except ValueError:

            print("Please enter a valid percentage.")

def choose_probability() -> float:

    print()

    print("Choose Probability Method\n")

    print("1. ⭐ Quick Confidence")
    print("2. 📊 Guided Analysis")
    print("3. 🎯 Advanced")

    while True:

        choice = input("\nChoice: ").strip()

        if choice == "1":
            return quick_probability()

        elif choice == "2":
            print("\nGuided Analysis coming in v2.5...\n")

        elif choice == "3":
            return advanced_probability()

        else:
            print("Please choose 1-3.")