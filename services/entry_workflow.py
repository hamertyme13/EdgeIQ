from services.entry_builder import build_entry

from ui.review_entry import review_entry
from ui.entry_analysis import display_entry_analysis

from repository.repositories.entry_repository import EntryRepository


def run_entry_workflow():

    entry = build_entry()

    if not review_entry(entry):

        print("\nEntry discarded.\n")

        return

    display_entry_analysis(entry)

    print()

    save = input(
        "Save this entry? (y/n): "
    ).strip().lower()

    if save == "y":

        EntryRepository.save(entry)

        print("\nEntry saved.\n")

    else:

        print("\nEntry discarded.\n")