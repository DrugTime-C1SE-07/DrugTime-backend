from dataclasses import dataclass
from datetime import date, datetime
from uuid import UUID

from drugtime.modules.identity.application.ports import AuthProvider, UserRepository
from drugtime.modules.identity.domain.profile import (
    ProfileRecord,
    normalize_contact_phone,
    validate_profile,
)
from drugtime.shared.errors import Conflict, Unauthorized


@dataclass(frozen=True)
class ProfileUpdateResult:
    previous_email: str | None
    auth_email_changed: bool


def get_profile(users: UserRepository, user_id: UUID) -> ProfileRecord:
    profile = users.get_profile(user_id)
    if profile is None:
        raise Unauthorized("Account does not exist or has been deleted")
    return profile


def update_profile(
    users: UserRepository,
    auth: AuthProvider,
    user_id: UUID,
    *,
    full_name: str,
    date_of_birth: date,
    gender: str,
    email: str | None = None,
    phone_number: str | None = None,
    at: datetime,
) -> ProfileUpdateResult:
    current = users.get_profile(user_id)
    if current is None:
        raise Unauthorized("Account does not exist or has been deleted")

    profile = validate_profile(
        full_name,
        date_of_birth,
        gender,
        current.email if email is None else email,
        at=at,
    )
    new_email = current.email if email is None else profile.email
    old_key = current.email.strip().lower() if current.email is not None else None
    new_key = new_email.strip().lower() if new_email is not None else None
    email_changed = old_key != new_key
    phone_fields = (
        {"phone_number": normalize_contact_phone(phone_number)} if phone_number is not None else {}
    )
    if email_changed:
        raise Conflict("email_change_verification_required")

    users.update_profile(
        user_id,
        full_name=profile.full_name,
        date_of_birth=date_of_birth,
        gender=profile.gender,
        # A concurrent verified email change owns this column.
        **phone_fields,
    )

    return ProfileUpdateResult(current.email, email_changed)
