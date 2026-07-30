from typing import Literal

from pydantic import BaseModel


class FinalStatsPayload(BaseModel):
    payload: str
    source: str = "manual"


class BettingHistoryPayload(BaseModel):
    payload: str
    source: str = "manual"


class UploadAnalyzePayload(BaseModel):
    file_name: str
    content_base64: str
    mime_type: str = ""
    target: Literal["entry", "props", "final_stats", "bet_history"] = "entry"
    source: str = "upload"


class ProviderWeightsPayload(BaseModel):
    weights: dict[str, float]
