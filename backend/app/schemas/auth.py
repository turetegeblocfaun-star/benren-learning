from __future__ import annotations

from datetime import datetime

from pydantic import Field

from app.schemas.common import ApiModel


class InviteSessionRequest(ApiModel):
    invite_code: str = Field(min_length=8, max_length=256)


class UserResponse(ApiModel):
    id: str
    status: str
    roles: list[str]
    capabilities: list[str]


class SessionResponse(ApiModel):
    user: UserResponse
    expires_at: datetime
