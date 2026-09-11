from pydantic import BaseModel, Field


class GamePropContextPayload(BaseModel):
    sport: str
    stat: str
    team: str
    game_prediction: dict
    expected_minutes: float | None = Field(default=None, ge=0)
    expected_opportunities: float | None = Field(default=None, ge=0)
