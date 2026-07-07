from rich.console import Console

from services.prop_builder import build_prop, choose_platform
from services.save_prop import save_prop

from ui.review import review_prop
from ui.prop_analysis import display_prop_analysis

console = Console()


def run_prop_builder():

    platform = choose_platform()

    prop = build_prop(platform)

    if not review_prop(prop):

        console.print("\nProp discarded.\n")

        return

    display_prop_analysis(prop)

    console.print()

    save = input(
        "Save this prop? (y/n): "
    ).strip().lower()

    if save == "y":

        save_prop(prop)

    else:

        console.print("\nProp not saved.\n")
