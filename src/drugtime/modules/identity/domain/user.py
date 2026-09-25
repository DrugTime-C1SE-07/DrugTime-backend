from dataclasses import dataclass
from datetime import date, datetime
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


class AccountType(StrEnum):
    PATIENT = "patient"
    FAMILY_MEMBER = "family_member"


class SessionType(StrEnum):
    MOBILE = "mobile"
    ADMIN_WEB = "admin_web"


@dataclass(frozen=True)
class RegistrationProfile:
    id: UUID
    email: str
    phone_number: str
    full_name: str
    date_of_birth: date
    gender: str
    account_type: AccountType


@dataclass(frozen=True)
class AppSession:
    token: str
    session_type: SessionType
    expires_at: datetime
    expires_in_seconds: int
