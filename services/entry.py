from models.entry import Entry
from models.player import Player
from models.prop import Prop
from models.stat_type import StatType

from analytics.edge import edge
from analytics.confidence import confidence


class EntryService:

    def create_prop(
        self,
        player_name: str,
        team: str,
        sport: str,
        stat: StatType,
        line: float,
        projection: float,
        ) -> Prop:

        player = Player(
            name=player_name,
            team=team,
            sport=sport,
        )

        edge_value = edge(line, projection)

        prop = Prop(
            player=player,
            stat=stat,
            line=line,
            projection=projection,
            edge=edge_value,
            confidence=confidence(
                edge_value
            ),
        )

        return prop
    
    def create_entry(
            self,
            platform: str,
        ) -> Entry:
        
        return Entry(
            platform=platform,
        )
    
    def add_prop(
            self,
            entry: Entry,
            prop: Prop,
        ) -> None:
        
        entry.props.append(prop)

    