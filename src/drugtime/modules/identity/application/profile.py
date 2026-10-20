import logging
from dataclasses import dataclass
from datetime import date, datetime
from uuid import UUID

from drugtime.modules.identity.application.ports import AuthProvider, UserRepository
from drugtime.modules.identity.domain.profile import ProfileRecord, validate_profile
from drugtime.shared.errors import ServiceUnavailable, Unauthorized

_LOGGER = logging.getLogger(__name__)


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
    email_changed = new_email != current.email
    if email_changed:
        auth.update_email(user_id, new_email)

    try:
        users.update_profile(
            user_id,
            full_name=profile.full_name,
            date_of_birth=date_of_birth,
            gender=profile.gender,
            email=new_email,
        )
    except Exception:
        if email_changed:
            try:
                auth.update_email(user_id, current.email)
            except Exception as rollback_error:
                _LOGGER.error(
                    "Could not restore Supabase email after profile DB update failed "
                    "for user %s",
                    user_id,
                )
                raise ServiceUnavailable("auth_provider_unavailable") from rollback_error
        raise

    return ProfileUpdateResult(current.email, email_changed)
