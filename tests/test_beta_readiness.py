from __future__ import annotations

from pathlib import Path

import pytest

from repository.database import SessionLocal, initialize_database
from repository.models.beta_feedback_model import BetaFeedbackModel
from repository.models.beta_issue_model import BetaIssueModel
from repository.models.beta_session_model import BetaSessionModel
from repository.models.beta_user_model import BetaUserModel
from repository.models.product_event_model import ProductEventModel
from repository.repositories.beta_feedback_repository import BetaFeedbackRepository, BetaIssueRepository
from repository.repositories.beta_user_repository import BetaUserRepository
from repository.repositories.product_experience_repository import ProductExperienceRepository
from services.beta_authentication import hash_password, verify_password
from web.application.beta_service import beta_summary

PASSWORD = "FoundingBetaPass123!"


@pytest.fixture(autouse=True)
def clean_beta_tables():
    initialize_database()
    with SessionLocal() as session:
        for model in (BetaFeedbackModel, BetaIssueModel, ProductEventModel, BetaSessionModel, BetaUserModel):
            session.query(model).delete()
        session.commit()
    yield
    with SessionLocal() as session:
        for model in (BetaFeedbackModel, BetaIssueModel, ProductEventModel, BetaSessionModel, BetaUserModel):
            session.query(model).delete()
        session.commit()


def create_user(**overrides) -> dict:
    values = {
        "email": "tester@example.com",
        "username": "founder1",
        "password": PASSWORD,
        "role": "BETA_TESTER",
        "beta_cohort": "FOUNDING_25",
    }
    values.update(overrides)
    return BetaUserRepository.create(**values)


def test_password_hashing_and_authentication_are_secure():
    encoded = hash_password(PASSWORD)
    assert PASSWORD not in encoded
    assert verify_password(PASSWORD, encoded)
    assert not verify_password("incorrect-password", encoded)


def test_create_authenticate_and_deactivate_beta_user():
    user = create_user(email=" Test@Example.com ", username="Founder.One")
    assert user["email"] == "test@example.com"
    assert user["username"] == "founder.one"
    assert user["role"] == "BETA_TESTER"
    assert BetaUserRepository.get_by_id(user["id"])["email"] == user["email"]
    assert BetaUserRepository.get_by_email(" TEST@example.com ")["id"] == user["id"]
    assert BetaUserRepository.get_by_username("Founder.One")["id"] == user["id"]
    assert BetaUserRepository.mark_last_active(user["id"])["last_active_at"]
    authenticated = BetaUserRepository.authenticate("TEST@example.com", PASSWORD)
    assert authenticated and authenticated["user"]["id"] == user["id"]
    assert BetaUserRepository.authenticate(user["email"], "wrong-password") is None
    assert BetaUserRepository.session_for_token(authenticated["token"])["session_id"] == authenticated["session_id"]
    BetaUserRepository.update(user["id"], is_active=False)
    assert BetaUserRepository.authenticate(user["email"], PASSWORD) is None
    assert BetaUserRepository.session_for_token(authenticated["token"]) is None


def test_duplicate_email_and_username_are_rejected():
    create_user()
    with pytest.raises(ValueError, match="already exists"):
        create_user(username="different")
    with pytest.raises(ValueError, match="already exists"):
        create_user(email="different@example.com")


def test_admin_role_and_onboarding_completion():
    user = create_user(role="ADMIN")
    assert user["is_admin"] is True
    completed = BetaUserRepository.complete_onboarding(user["id"])
    assert completed["onboarding_complete"] is True


def test_legacy_and_attributed_product_events_remain_supported():
    legacy = ProductExperienceRepository.record_event("recommendation_viewed", "prop", "legacy")
    assert legacy["id"]
    user = create_user()
    authenticated = BetaUserRepository.authenticate(user["email"], PASSWORD)
    ProductExperienceRepository.record_event(
        "entry_analyzed",
        "entry",
        "12",
        user_id=user["id"],
        session_id=authenticated["session_id"],
    )
    assert ProductExperienceRepository.event_counts(user_id=user["id"])["entry_analyzed"] == 1
    assert ProductExperienceRepository.analytics()["funnel"][0]["count"] == 1


def test_settlement_event_inherits_saved_entry_owner():
    user = create_user()
    authenticated = BetaUserRepository.authenticate(user["email"], PASSWORD)
    ProductExperienceRepository.record_event(
        "entry_saved", "entry", "44", user_id=user["id"], session_id=authenticated["session_id"]
    )
    ProductExperienceRepository.record_event("entry_settled", "entry", "44")
    assert ProductExperienceRepository.event_counts(user_id=user["id"])["entry_settled"] == 1


def test_feedback_links_context_calculates_change_and_updates_duplicate():
    user = create_user()
    authenticated = BetaUserRepository.authenticate(user["email"], PASSWORD)
    payload = {
        "prediction_record_id": None,
        "entry_id": None,
        "entry_prop_id": None,
        "useful": True,
        "initial_pick": "Under",
        "final_pick": "Over",
        "would_pick": "Yes",
        "would_pay": "$19.99/month",
        "feedback_text": "Opponent history changed my view.",
        "context": {"player": "Test Player", "stat": "Points", "line": 19.5},
    }
    first = BetaFeedbackRepository.submit(user["id"], authenticated["session_id"], payload)
    second = BetaFeedbackRepository.submit(user["id"], authenticated["session_id"], {**payload, "useful": False})
    assert first["changed_decision"] is True
    assert second["id"] == first["id"]
    assert BetaFeedbackRepository.for_prediction(999999) == []
    aggregate = BetaFeedbackRepository.aggregate()
    assert aggregate["total_feedback"] == 1
    assert aggregate["decision_change_rate"] == 100.0
    assert aggregate["would_pay_distribution"]["$19.99/month"] == 1


def test_bug_and_feature_requests_are_structured_and_reviewable():
    user = create_user()
    authenticated = BetaUserRepository.authenticate(user["email"], PASSWORD)
    bug = BetaIssueRepository.submit(user["id"], authenticated["session_id"], {
        "issue_type": "BUG", "category": "Wrong line", "description": "The displayed line was stale."
    })
    feature = BetaIssueRepository.submit(user["id"], authenticated["session_id"], {
        "issue_type": "FEATURE", "category": "Feature request", "description": "Add a compact export view."
    })
    assert bug["normalized_key"] == "displayed line was stale"
    assert feature["issue_type"] == "FEATURE"
    assert BetaIssueRepository.counts() == {"BUG": 1, "FEATURE": 1}
    assert BetaIssueRepository.recent(5, "BUG")[0]["tester"] == user["username"]


def test_beta_summary_handles_zero_and_single_tester_states():
    empty = beta_summary()
    assert empty["testers"] == 0
    assert empty["useful_rate"] == 0.0
    user = create_user()
    authenticated = BetaUserRepository.authenticate(user["email"], PASSWORD)
    ProductExperienceRepository.record_event(
        "entry_analyzed", "entry", "1", user_id=user["id"], session_id=authenticated["session_id"]
    )
    ProductExperienceRepository.record_event("recommendation_viewed", "prop", "anonymous")
    BetaFeedbackRepository.submit(user["id"], authenticated["session_id"], {
        "useful": True,
        "initial_pick": "Unsure",
        "final_pick": "Under",
        "would_pick": "Yes",
        "would_pay": "Free",
        "context": {"player": "Example"},
    })
    summary = beta_summary()
    assert summary["testers"] == 1
    assert summary["sessions"] == 1
    assert summary["analyses"] == 1
    assert summary["funnel"][0]["count"] == 0
    assert summary["funnel"][1]["count"] == 1
    assert summary["feedback_responses"] == 1
    assert summary["useful_rate"] == 100.0
    assert summary["testers_activity"][0]["feedback"] == 1
    assert "verified_predictions" in summary["model_performance"]
    assert "distribution_coverage" in summary["model_performance"]


def test_beta_browser_surface_is_present():
    html = Path("web/static/index.html").read_text(encoding="utf-8")
    assert 'id="beta-center-toggle"' in html
    assert 'id="beta-feedback-form"' in html
    assert 'id="beta-admin-panel"' in html
    assert "/static/js/beta.js" in html


def test_beta_management_wrapper_selects_a_dependency_ready_python():
    script = Path("scripts/manage_beta.sh").read_text(encoding="utf-8")
    assert "import alembic, sqlalchemy" in script
    assert 'scripts/manage_beta.py "$@"' in script
