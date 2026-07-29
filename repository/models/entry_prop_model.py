from sqlalchemy import (
    Boolean,
    Column,
    Float,
    ForeignKey,
    Integer,
    String,
)

from repository.database import Base


class EntryPropModel(Base):

    __tablename__ = "entry_props"

    id = Column(Integer, primary_key=True)

    entry_id = Column(
        Integer,
        ForeignKey("entries.id"),
        nullable=False,
    )

    player_name = Column(String)

    player_identity_id = Column(Integer)

    player_provider = Column(String, default="")

    provider_player_id = Column(String, default="")

    team = Column(String)

    sport = Column(String)

    stat = Column(String)

    line = Column(Float)

    projection = Column(Float)

    edge = Column(Float)

    confidence = Column(Float)

    direction = Column(String)

    platform = Column(String)

    game = Column(String)

    game_time = Column(String, default="")

    position = Column(String, default="")

    baseline_line = Column(Float)

    standard_line = Column(Float)

    line_offer_type = Column(String, default="standard")

    adjusted_line = Column(Boolean, default=False)

    is_discounted_line = Column(Boolean, default=False)

    is_premium_line = Column(Boolean, default=False)

    line_discount = Column(Float, default=0.0)

    projection_source = Column(String, default="")

    auto_projected = Column(Boolean, default=False)

    actual = Column(Float)

    final_result = Column(String, default="")

    final_source = Column(String, default="")

    final_status = Column(String, default="")
