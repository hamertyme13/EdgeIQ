from dataclasses import dataclass

from models.player import Player
from models.platform import Platform
from models.stat_type import StatType


@dataclass
class Prop:

    player: Player

    stat: StatType

    line: float

    projection: float

    edge: float

    confidence: float

    direction: str = "Over"

    platform: Platform = Platform.PRIZEPICKS

    game: str = ""

    game_time: str = ""

    position: str = ""

    season_type: str = ""

    needs_projection: bool = False

    auto_projected: bool = False

    trending_count: int = 0

    projection_source: str = "user"

    baseline_line: float | None = None

    standard_line: float | None = None

    line_offer_type: str = "standard"

    adjusted_line: bool = False

    is_discounted_line: bool = False

    is_premium_line: bool = False

    line_discount: float = 0.0

    espn_recent_average: float | None = None

    espn_hit_rate: float | None = None

    espn_sample_size: int = 0

    espn_note: str = ""

    confidence_adjustment: float = 0.0

    source_signals: list[dict] | None = None

    source_score: float = 0.0

    player_identity_id: int | None = None

    player_provider: str = ""

    provider_player_id: str = ""
