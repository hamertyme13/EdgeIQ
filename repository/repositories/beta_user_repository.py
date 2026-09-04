from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError

from repository.database import SessionLocal, initialize_database
from repository.models.beta_session_model import BetaSessionModel
from repository.models.beta_user_model import BetaUserModel
from services.beta_authentication import hash_password, hash_session_token, new_session_token, verify_password
from utils.time import utc_now

ROLES = {"ADMIN", "BETA_TESTER"}


class BetaUserRepository:
    @staticmethod
    def create(
        email: str,
        username: str,
        password: str,
        *,
        role: str = "BETA_TESTER",
        beta_cohort: str = "FOUNDING_25",
        is_beta_tester: bool = True,
    ) -> dict:
        initialize_database()
        normalized_email = _normalize_email(email)
        normalized_username = _normalize_username(username)
        normalized_role = role.strip().upper()
        if normalized_role not in ROLES:
            raise ValueError("Role must be ADMIN or BETA_TESTER.")
        with SessionLocal() as session:
            row = BetaUserModel(
                email=normalized_email,
                username=normalized_username,
                password_hash=hash_password(password),
                role=normalized_role,
                is_beta_tester=bool(is_beta_tester),
                beta_cohort=(beta_cohort.strip().upper() or "FOUNDING_25")[:40],
                is_active=True,
            )
            session.add(row)
            try:
                session.commit()
            except IntegrityError as error:
                session.rollback()
                raise ValueError("A beta account with that email or username already exists.") from error
            session.refresh(row)
            return _user_payload(row)

    @staticmethod
    def authenticate(identifier: str, password: str, *, days: int = 14) -> dict | None:
        initialize_database()
        lookup = identifier.strip().lower()
        now = utc_now().replace(tzinfo=None)
        with SessionLocal() as session:
            user = session.query(BetaUserModel).filter(
                or_(BetaUserModel.email == lookup, BetaUserModel.username == lookup)
            ).one_or_none()
            if user is None or not user.is_active or not verify_password(password, user.password_hash):
                return None
            token = new_session_token()
            beta_session = BetaSessionModel(
                id=str(uuid4()),
                user_id=user.id,
                token_hash=hash_session_token(token),
                started_at=now,
                last_active_at=now,
                expires_at=now + timedelta(days=max(1, min(days, 30))),
            )
            user.last_active_at = now
            session.add(beta_session)
            session.commit()
            return {"token": token, "session_id": beta_session.id, "user": _user_payload(user)}

    @staticmethod
    def get_by_id(user_id: int) -> dict | None:
        initialize_database()
        with SessionLocal() as session:
            row = session.get(BetaUserModel, int(user_id))
            return _user_payload(row) if row is not None else None

    @staticmethod
    def get_by_email(email: str) -> dict | None:
        initialize_database()
        normalized = _normalize_email(email)
        with SessionLocal() as session:
            row = session.query(BetaUserModel).filter_by(email=normalized).one_or_none()
            return _user_payload(row) if row is not None else None

    @staticmethod
    def get_by_username(username: str) -> dict | None:
        initialize_database()
        normalized = _normalize_username(username)
        with SessionLocal() as session:
            row = session.query(BetaUserModel).filter_by(username=normalized).one_or_none()
            return _user_payload(row) if row is not None else None

    @staticmethod
    def mark_last_active(user_id: int) -> dict | None:
        initialize_database()
        with SessionLocal() as session:
            row = session.get(BetaUserModel, int(user_id))
            if row is None:
                return None
            row.last_active_at = utc_now().replace(tzinfo=None)
            session.commit()
            return _user_payload(row)

    @staticmethod
    def session_for_token(token: str, *, touch: bool = True) -> dict | None:
        if not token:
            return None
        initialize_database()
        now = utc_now().replace(tzinfo=None)
        with SessionLocal() as session:
            row = session.query(BetaSessionModel).filter_by(token_hash=hash_session_token(token)).one_or_none()
            if row is None or row.ended_at is not None or row.expires_at <= now:
                return None
            user = session.get(BetaUserModel, row.user_id)
            if user is None or not user.is_active:
                return None
            if touch:
                row.last_active_at = now
                user.last_active_at = now
                session.commit()
            return {"session_id": row.id, "user": _user_payload(user), "expires_at": row.expires_at.isoformat()}

    @staticmethod
    def logout(token: str) -> bool:
        initialize_database()
        with SessionLocal() as session:
            row = session.query(BetaSessionModel).filter_by(token_hash=hash_session_token(token)).one_or_none()
            if row is None:
                return False
            row.ended_at = utc_now().replace(tzinfo=None)
            session.commit()
            return True

    @staticmethod
    def list_beta_users() -> list[dict]:
        initialize_database()
        with SessionLocal() as session:
            rows = session.query(BetaUserModel).filter(BetaUserModel.is_beta_tester.is_(True)).order_by(
                BetaUserModel.created_at.asc()
            ).all()
            return [_user_payload(row) for row in rows]

    @staticmethod
    def update(user_id: int, *, is_active: bool | None = None, beta_cohort: str | None = None) -> dict | None:
        initialize_database()
        with SessionLocal() as session:
            row = session.get(BetaUserModel, int(user_id))
            if row is None:
                return None
            if is_active is not None:
                row.is_active = bool(is_active)
            if beta_cohort is not None:
                row.beta_cohort = (beta_cohort.strip().upper() or "FOUNDING_25")[:40]
            session.commit()
            return _user_payload(row)

    @staticmethod
    def complete_onboarding(user_id: int) -> dict | None:
        initialize_database()
        with SessionLocal() as session:
            row = session.get(BetaUserModel, int(user_id))
            if row is None:
                return None
            if row.onboarding_completed_at is None:
                row.onboarding_completed_at = utc_now().replace(tzinfo=None)
            row.last_active_at = utc_now().replace(tzinfo=None)
            session.commit()
            return _user_payload(row)

    @staticmethod
    def count() -> int:
        initialize_database()
        with SessionLocal() as session:
            return session.query(BetaUserModel).count()


def _normalize_email(value: str) -> str:
    email = value.strip().lower()
    if len(email) > 320 or "@" not in email or email.startswith("@") or email.endswith("@"):
        raise ValueError("Enter a valid email address.")
    return email


def _normalize_username(value: str) -> str:
    username = value.strip().lower()
    if not 3 <= len(username) <= 80 or not all(character.isalnum() or character in "._-" for character in username):
        raise ValueError("Username must be 3-80 characters using letters, numbers, dots, dashes, or underscores.")
    return username


def _user_payload(row: BetaUserModel) -> dict:
    return {
        "id": row.id,
        "email": row.email,
        "username": row.username,
        "role": row.role,
        "is_admin": row.role == "ADMIN",
        "is_beta_tester": bool(row.is_beta_tester),
        "beta_cohort": row.beta_cohort,
        "is_active": bool(row.is_active),
        "onboarding_complete": row.onboarding_completed_at is not None,
        "created_at": row.created_at.isoformat() if row.created_at else "",
        "last_active_at": row.last_active_at.isoformat() if row.last_active_at else "",
    }
