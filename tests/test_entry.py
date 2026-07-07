from models.entry import Entry
from models.platform import Platform


def test_entry_defaults_to_empty_props():
    entry = Entry(platform=Platform.PRIZEPICKS)

    assert entry.prop_count == 0
    assert entry.average_confidence == 0
    assert entry.average_edge == 0
    assert entry.is_empty is True
