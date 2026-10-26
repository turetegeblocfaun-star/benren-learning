from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.errors import ApiError
from app.core.security import session_token_hash
from app.core.time import ensure_utc, utc_now
from app.db import get_db
from app.models.entities import AuthSession, Course, Material, OrganizationMembership, User
from app.models.enums import MaterialStatus, MembershipRole, UserStatus

DbSession = Annotated[Session, Depends(get_db)]
AppSettings = Annotated[Settings, Depends(get_settings)]


def get_current_user(
    request: Request,
    db: DbSession,
    settings: AppSettings,
) -> User:
    bl_session = request.cookies.get(settings.session_cookie_name)
    if not bl_session:
        raise ApiError("UNAUTHENTICATED", "请先登录后再继续。", status_code=401)
    digest = session_token_hash(bl_session, settings.session_signing_key.get_secret_value())
    auth_session = db.scalar(
        select(AuthSession).where(
            AuthSession.token_hash == digest, AuthSession.revoked_at.is_(None)
        )
    )
    if auth_session is None or ensure_utc(auth_session.expires_at) <= utc_now():
        raise ApiError("UNAUTHENTICATED", "登录状态已失效，请重新登录。", status_code=401)
    user = db.get(User, auth_session.user_id)
    if user is None or user.status != UserStatus.ACTIVE:
        raise ApiError("UNAUTHENTICATED", "当前账号不可用。", status_code=401)
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def user_access_profile(
    db: Session, user: User, settings: Settings
) -> tuple[list[str], list[str]]:
    memberships = list(
        db.scalars(
            select(OrganizationMembership).where(OrganizationMembership.user_id == user.id)
        )
    )
    roles = {"learner"}
    capabilities = {
        "learning:p0",
        "practice:subjective",
        "calendar:external",
        "organization:create",
        "cross_course:manage",
        "sft:manage",
    }
    for membership in memberships:
        roles.add(f"organization_{membership.role}")
        if membership.role in {MembershipRole.OWNER, MembershipRole.ADMIN}:
            capabilities.add("organization:manage")
    if (
        settings.app_env != "production"
        or user.auth_subject_hash in settings.internal_governance_subject_hashes
    ):
        roles.add("internal_governance")
        capabilities.add("governance:read")
    return sorted(roles), sorted(capabilities)


def require_capability(
    db: Session, user: User, settings: Settings, capability: str
) -> None:
    _, capabilities = user_access_profile(db, user, settings)
    if capability not in capabilities:
        raise ApiError("FORBIDDEN", "当前账号没有使用该能力的权限。", status_code=403)


def owned_course(db: Session, user: User, course_id: str) -> Course:
    course = db.scalar(
        select(Course).where(Course.id == course_id, Course.owner_user_id == user.id)
    )
    if course is None:
        raise ApiError("FORBIDDEN", "你无权访问这个课程。", status_code=403)
    return course


def owned_material(
    db: Session,
    user: User,
    material_id: str,
    *,
    include_deleted: bool = False,
) -> Material:
    conditions = [Material.id == material_id, Material.owner_user_id == user.id]
    if not include_deleted:
        conditions.append(Material.status.notin_([MaterialStatus.DELETING, MaterialStatus.DELETED]))
    material = db.scalar(select(Material).where(*conditions))
    if material is None:
        raise ApiError("FORBIDDEN", "你无权访问这份材料。", status_code=403)
    return material
