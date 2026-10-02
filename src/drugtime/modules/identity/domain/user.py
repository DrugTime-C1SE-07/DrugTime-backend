from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID


@dataclass(frozen=True)
class CurrentUser:
    id: UUID
    is_admin: bool


@dataclass(frozen=True)
class UserRecord:
    id: UUID
    is_admin: bool
    erased: bool
    profile_complete: bool


class SessionType(StrEnum):
    MOBILE = "mobile"
    ADMIN_WEB = "admin_web"


@dataclass(frozen=True)
class AppSession:
    token: str
    session_type: SessionType
    expires_at: datetime
    expires_in_seconds: int
