from rich.console import Console

from services.entry_builder import build_entry

from ui.review_entry import review_entry
from ui.entry_analysis import display_entry_analysis

from repository.repositories.entry_repository import EntryRepository

console = Console()


def run_entry_workflow():

    entry = build_entry()

    if not review_entry(entry):

        console.print("\nEntry discarded.\n")

        return

    display_entry_analysis(entry)

    console.print()

    save = input(
        "Save this entry? (y/n): "
    ).strip().lower()

    if save == "y":

        EntryRepository.save(entry)

        console.print("\nEntry saved.\n")

    else:

        console.print("\nEntry discarded.\n")
