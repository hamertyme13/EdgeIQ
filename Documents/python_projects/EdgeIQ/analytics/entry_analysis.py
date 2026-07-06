from models.entry import Entry
from models.prop import Prop

from analytics.entry_recommendation import recommendation


def strongest_prop(entry: Entry) -> Prop:
    """Return the prop with the highest edge."""

    return max(entry.props, key=lambda prop: prop.edge)


def weakest_prop(entry: Entry) -> Prop:
    """Return the prop with the lowest edge."""

    return min(entry.props, key=lambda prop: prop.edge)