from models.entry import Entry
from services.prop_builder import build_prop, choose_platform


def build_entry() -> Entry:
    """Build a complete betting entry."""

    # Build the first prop
    platform = choose_platform()

    entry = Entry(
        platform=platform
    )

    first_prop = build_prop(platform)

    entry.add_prop(first_prop)

    while True:

        print()

        another = input(
            "Add another prop? (y/n): "
        ).strip().lower()

        if another != "y":
            break

        prop = build_prop(platform)

        entry.add_prop(prop)

    return entry