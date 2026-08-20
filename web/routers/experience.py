import json

from fastapi import APIRouter

from repository.repositories.product_experience_repository import ProductExperienceRepository
from repository.repositories.settings_repository import SettingsRepository
from web.schemas.experience import OnboardingPayload, ProductEventPayload, ResearchHistoryPayload

router = APIRouter(prefix="/api/experience", tags=["experience"])


@router.post("/events")
def record_event(payload: ProductEventPayload) -> dict:
    return ProductExperienceRepository.record_event(payload.event_name, payload.entity_type, payload.entity_id, payload.metadata)


@router.get("/analytics")
def product_analytics() -> dict:
    return ProductExperienceRepository.analytics()


@router.get("/research-history")
def research_history(limit: int = 12) -> dict:
    return {"history": ProductExperienceRepository.recent_research(limit)}


@router.post("/research-history")
def save_research_history(payload: ResearchHistoryPayload) -> dict:
    return ProductExperienceRepository.save_research(payload.model_dump())


@router.get("/onboarding")
def onboarding() -> dict:
    raw = SettingsRepository.get("onboarding_profile", "")
    return json.loads(raw) if raw else {"complete": False}


@router.post("/onboarding")
def save_onboarding(payload: OnboardingPayload) -> dict:
    data = payload.model_dump()
    SettingsRepository.set("onboarding_profile", json.dumps(data, sort_keys=True))
    return data
