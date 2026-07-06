from models.entry import Entry
from models.platform import Platform

entry = Entry(
    platform=Platform.PRIZEPICKS
)

print(entry.prop_count)