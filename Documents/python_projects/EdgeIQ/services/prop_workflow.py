from services.prop_builder import build_prop
from services.save_prop import save_prop

from ui.review import review_prop
from ui.prop_analysis import display_prop_analysis


def run_prop_builder():

    prop = build_prop()

    if not review_prop(prop):

        print("\nProp discarded.\n")

        return

    display_prop_analysis(prop)

    print()

    save = input(
        "Save this prop? (y/n): "
    ).strip().lower()

    if save == "y":

        save_prop(prop)

    else:

        print("\nProp not saved.\n")