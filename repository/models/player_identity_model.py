from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, UniqueConstraint, func

from repository.database import Base


class PlayerIdentityModel(Base):
    __tablename__ = "player_identities"

    id = Column(Integer, primary_key=True)
    canonical_name = Column(String, nullable=False)
    canonical_key = Column(String, nullable=False, index=True)
    sport = Column(String, nullable=False, default="", index=True)
    current_team = Column(String, nullable=False, default="")
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("canonical_key", "sport", name="uq_player_identity_key_sport"),
    )


class PlayerAliasModel(Base):
    __tablename__ = "player_aliases"

    id = Column(Integer, primary_key=True)
    identity_id = Column(Integer, ForeignKey("player_identities.id"), nullable=False, index=True)
    provider = Column(String, nullable=False, default="", index=True)
    # NULL keeps name-only aliases out of the provider-ID uniqueness constraint.
    provider_player_id = Column(String, nullable=True, index=True)
    alias_name = Column(String, nullable=False)
    alias_key = Column(String, nullable=False, index=True)
    sport = Column(String, nullable=False, default="", index=True)
    team = Column(String, nullable=False, default="")
    last_seen_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("provider", "provider_player_id", name="uq_player_alias_provider_id"),
        UniqueConstraint("identity_id", "provider", "alias_key", name="uq_player_alias_identity_provider_name"),
    )
