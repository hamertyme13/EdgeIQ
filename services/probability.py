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

    console.print("\nHow confident are you that this prop will hit?\n")

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
                console.print(f"\n✓ Your estimated probability is {probability:.1f}%")
                console.print(f"✓ Confidence Level: {label}\n")
                console.print("EdgeIQ uses this probability to calculate Expected Value (EV) for your bet.")
                return probability

            console.print("Choose a number between 1 and 5.")

        except ValueError:

            console.print("Please enter a valid number.")

def advanced_probability() -> float:

    while True:

        try:

            probability = float(
                input("\nProjected Win Probability (%): ")
            )

            if 0 <= probability <= 100:
                return probability

            console.print("Enter a value between 0 and 100.")

        except ValueError:

            console.print("Please enter a valid percentage.")

def choose_probability() -> float:

    console.print()

    console.print("Choose Probability Method\n")

    console.print("1. ⭐ Quick Confidence")
    console.print("2. 📊 Guided Analysis [dim](coming soon)[/dim]")
    console.print("3. 🎯 Advanced")

    while True:

        choice = input("\nChoice: ").strip()

        if choice == "1":
            return quick_probability()

        elif choice == "2":
            console.print("\n[dim]Guided Analysis coming in v2.5...[/dim]\n")

        elif choice == "3":
            return advanced_probability()

        else:
            console.print("Please choose 1-3.")
