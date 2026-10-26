from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Request, Response
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.api.deps import AppSettings, CurrentUser, DbSession, user_access_profile
from app.core.errors import ApiError
from app.core.security import (
    new_session_token,
    session_token_hash,
    verify_invite_code,
    verify_timed_invite_code,
)
from app.core.time import utc_now
from app.models.entities import AuthSession, User
from app.schemas.auth import InviteSessionRequest, SessionResponse, UserResponse
from app.services.audit import audit

router = APIRouter(tags=["auth"])


def _user_response(db: DbSession, settings: AppSettings, user: User) -> UserResponse:
    roles, capabilities = user_access_profile(db, user, settings)
    return UserResponse(
        id=user.id,
        status=user.status,
        roles=roles,
        capabilities=capabilities,
    )


@router.post("/auth/invite-session", response_model=SessionResponse)
def create_invite_session(
    body: InviteSessionRequest,
    request: Request,
    response: Response,
    db: DbSession,
    settings: AppSettings,
) -> SessionResponse:
    valid_permanent_invite = bool(settings.invite_code_hashes) and verify_invite_code(
        body.invite_code, settings.invite_code_hashes
    )
    valid_timed_invite = bool(settings.timed_invite_code_hashes) and verify_timed_invite_code(
        body.invite_code, settings.timed_invite_code_hashes
    )
    if not (valid_permanent_invite or valid_timed_invite):
        audit(
            db,
            user_id=None,
            action="invite_login",
            target_type="session",
            result="denied",
            request_id=request.state.request_id,
        )
        db.commit()
        raise ApiError("INVALID_INVITE", "邀请码无效或已停用。", status_code=401)
    signing_key = settings.session_signing_key.get_secret_value()
    subject_hash = session_token_hash(body.invite_code, signing_key)
    user = db.scalar(select(User).where(User.auth_subject_hash == subject_hash))
    if user is None:
        user = User(auth_subject_hash=subject_hash)
        db.add(user)
        try:
            db.flush()
        except IntegrityError:
            # Two browsers can redeem the same valid invite at the same time.
            # The unique subject hash is the authority: discard the losing
            # insert and continue with the user committed by the other request.
            db.rollback()
            user = db.scalar(select(User).where(User.auth_subject_hash == subject_hash))
            if user is None:
                raise
    raw_token = new_session_token()
    expires_at = utc_now() + timedelta(hours=settings.session_ttl_hours)
    db.add(
        AuthSession(
            user_id=user.id,
            token_hash=session_token_hash(raw_token, signing_key),
            expires_at=expires_at,
        )
    )
    audit(
        db,
        user_id=user.id,
        action="invite_login",
        target_type="session",
        result="succeeded",
        request_id=request.state.request_id,
    )
    db.commit()
    response.set_cookie(
        settings.session_cookie_name,
        raw_token,
        max_age=settings.session_ttl_hours * 3600,
        httponly=True,
        secure=settings.app_env == "production",
        samesite="lax",
        path="/",
    )
    return SessionResponse(user=_user_response(db, settings, user), expires_at=expires_at)


@router.get("/me", response_model=UserResponse)
def me(db: DbSession, settings: AppSettings, user: CurrentUser) -> UserResponse:
    return _user_response(db, settings, user)
