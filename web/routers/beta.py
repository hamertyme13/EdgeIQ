from __future__ import annotations

import hmac
import os

from fastapi import APIRouter, HTTPException, Request

from repository.repositories.beta_feedback_repository import BetaFeedbackRepository, BetaIssueRepository
from repository.repositories.beta_user_repository import BetaUserRepository
from repository.repositories.product_experience_repository import ProductExperienceRepository
from web.application.beta_service import beta_summary
from web.schemas.beta import (
    BetaBootstrapPayload,
    BetaFeedbackPayload,
    BetaInitialDecisionPayload,
    BetaIssuePayload,
    BetaLoginPayload,
    BetaUserCreatePayload,
    BetaUserUpdatePayload,
)

router = APIRouter(prefix="/api/beta", tags=["beta"])


def beta_session_from_request(request: Request, *, required: bool = False, admin: bool = False) -> dict | None:
    authorization = request.headers.get("authorization", "")
    token = authorization[7:].strip() if authorization.lower().startswith("bearer ") else ""
    session = BetaUserRepository.session_for_token(token) if token else None
    if required and session is None:
        raise HTTPException(status_code=401, detail="Sign in with an active Founding Beta account to continue.")
    if admin and not session["user"]["is_admin"]:
        raise HTTPException(status_code=403, detail="This Founding Beta action is available to administrators only.")
    return session


@router.get("/status")
def beta_status(request: Request) -> dict:
    session = beta_session_from_request(request)
    return {
        "configured": BetaUserRepository.count() > 0,
        "authenticated": session is not None,
        "session": session,
        "responsible_use": (
            "EdgeIQ provides statistical analysis and decision-support tools for informational and entertainment "
            "purposes. Predictions do not guarantee outcomes or financial returns. Sports wagering involves risk, "
            "and users are responsible for their own decisions."
        ),
    }


@router.post("/bootstrap")
def bootstrap_admin(payload: BetaBootstrapPayload) -> dict:
    configured = os.getenv("EDGEIQ_BETA_BOOTSTRAP_TOKEN", "")
    if not configured or not hmac.compare_digest(payload.bootstrap_token, configured):
        raise HTTPException(status_code=403, detail="The beta bootstrap token was not accepted.")
    if BetaUserRepository.count() > 0:
        raise HTTPException(status_code=409, detail="Beta identity is already initialized. Sign in as an administrator.")
    try:
        return {"user": BetaUserRepository.create(**payload.model_dump(exclude={"bootstrap_token"}))}
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.post("/login")
def login(payload: BetaLoginPayload) -> dict:
    authenticated = BetaUserRepository.authenticate(payload.identifier, payload.password)
    if authenticated is None:
        raise HTTPException(status_code=401, detail="Email, username, or password was not recognized.")
    user = authenticated["user"]
    ProductExperienceRepository.record_event(
        "beta_login",
        "user",
        str(user["id"]),
        user_id=user["id"],
        session_id=authenticated["session_id"],
    )
    ProductExperienceRepository.record_event(
        "beta_session_started",
        "session",
        authenticated["session_id"],
        user_id=user["id"],
        session_id=authenticated["session_id"],
    )
    return authenticated


@router.post("/logout")
def logout(request: Request) -> dict:
    session = beta_session_from_request(request, required=True)
    authorization = request.headers.get("authorization", "")
    token = authorization[7:].strip()
    ProductExperienceRepository.record_event(
        "beta_logout",
        "user",
        str(session["user"]["id"]),
        user_id=session["user"]["id"],
        session_id=session["session_id"],
    )
    ProductExperienceRepository.record_event(
        "beta_session_ended",
        "session",
        session["session_id"],
        user_id=session["user"]["id"],
        session_id=session["session_id"],
    )
    BetaUserRepository.logout(token)
    return {"logged_out": True}


@router.post("/onboarding")
def complete_onboarding(request: Request) -> dict:
    session = beta_session_from_request(request, required=True)
    user = BetaUserRepository.complete_onboarding(session["user"]["id"])
    ProductExperienceRepository.record_event(
        "beta_onboarding_completed",
        "user",
        str(user["id"]),
        user_id=user["id"],
        session_id=session["session_id"],
    )
    return {"user": user}


@router.post("/feedback")
def submit_feedback(payload: BetaFeedbackPayload, request: Request) -> dict:
    session = beta_session_from_request(request, required=True)
    try:
        feedback = BetaFeedbackRepository.submit(
            session["user"]["id"], session["session_id"], payload.model_dump()
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    ProductExperienceRepository.record_event(
        "feedback_submitted",
        "prediction" if feedback["prediction_record_id"] else "analysis",
        str(feedback["prediction_record_id"] or feedback["id"]),
        {"useful": feedback["useful"], "changed_decision": feedback["changed_decision"]},
        user_id=session["user"]["id"],
        session_id=session["session_id"],
    )
    if feedback["changed_decision"]:
        ProductExperienceRepository.record_event(
            "decision_changed",
            "feedback",
            str(feedback["id"]),
            user_id=session["user"]["id"],
            session_id=session["session_id"],
        )
    return {"feedback": feedback}


@router.post("/decisions/initial")
def record_initial_decision(payload: BetaInitialDecisionPayload, request: Request) -> dict:
    session = beta_session_from_request(request, required=True)
    event = ProductExperienceRepository.record_event(
        "initial_opinion_recorded",
        "analysis",
        str(payload.context.get("prediction_record_id") or payload.context.get("player") or "manual"),
        {"initial_pick": payload.initial_pick, "context": payload.context},
        user_id=session["user"]["id"],
        session_id=session["session_id"],
    )
    return {"recorded": True, "event": event}


@router.get("/feedback")
def user_feedback(request: Request, limit: int = 30) -> dict:
    session = beta_session_from_request(request, required=True)
    return {"feedback": BetaFeedbackRepository.recent(limit, user_id=session["user"]["id"])}


@router.post("/issues")
def submit_issue(payload: BetaIssuePayload, request: Request) -> dict:
    session = beta_session_from_request(request, required=True)
    try:
        issue = BetaIssueRepository.submit(session["user"]["id"], session["session_id"], payload.model_dump())
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    event_name = "bug_reported" if issue["issue_type"] == "BUG" else "feature_requested"
    ProductExperienceRepository.record_event(
        event_name,
        "beta_issue",
        str(issue["id"]),
        {"category": issue["category"]},
        user_id=session["user"]["id"],
        session_id=session["session_id"],
    )
    return {"issue": issue}


@router.get("/admin/summary")
def admin_summary(request: Request) -> dict:
    beta_session_from_request(request, required=True, admin=True)
    return beta_summary()


@router.get("/admin/users")
def admin_users(request: Request) -> dict:
    beta_session_from_request(request, required=True, admin=True)
    return {"users": BetaUserRepository.list_beta_users()}


@router.post("/admin/users")
def create_beta_user(payload: BetaUserCreatePayload, request: Request) -> dict:
    session = beta_session_from_request(request, required=True, admin=True)
    try:
        user = BetaUserRepository.create(**payload.model_dump())
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    ProductExperienceRepository.record_event(
        "beta_user_created",
        "user",
        str(user["id"]),
        {"cohort": user["beta_cohort"], "role": user["role"]},
        user_id=session["user"]["id"],
        session_id=session["session_id"],
    )
    return {"user": user}


@router.patch("/admin/users/{user_id}")
def update_beta_user(user_id: int, payload: BetaUserUpdatePayload, request: Request) -> dict:
    beta_session_from_request(request, required=True, admin=True)
    user = BetaUserRepository.update(user_id, **payload.model_dump())
    if user is None:
        raise HTTPException(status_code=404, detail="Beta tester was not found.")
    return {"user": user}
