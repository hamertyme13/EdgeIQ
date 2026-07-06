from services.entry import EntryService
from models.stat_type import StatType
from ui.entry_view import display_entry

service = EntryService()

entry = service.create_entry("PrizePicks")

prop = service.create_prop(
    player_name="Caitlin Clark",
    team="Indiana Fever",
    sport="WNBA",
    stat=StatType.ASSISTS,
    line=8.5,
    projection=9.7,
)

service.add_prop(entry, prop)

display_entry(entry)