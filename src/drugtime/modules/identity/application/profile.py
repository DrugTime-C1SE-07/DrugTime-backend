from datetime import date, datetime
from uuid import UUID

from drugtime.modules.identity.application.ports import UserRepository
from drugtime.modules.identity.domain.profile import ProfileRecord, validate_profile
from drugtime.shared.errors import Unauthorized


def get_profile(users: UserRepository, user_id: UUID) -> ProfileRecord:
    profile = users.get_profile(user_id)
    if profile is None:
        raise Unauthorized("Account does not exist or has been deleted")
    return profile


def update_profile(
    users: UserRepository,
    user_id: UUID,
    *,
    full_name: str,
    date_of_birth: date,
    gender: str,
    at: datetime,
) -> None:
    profile = validate_profile(full_name, date_of_birth, gender, at=at)
    get_profile(users, user_id)
    users.update_profile(
        user_id, full_name=profile.full_name, date_of_birth=date_of_birth, gender=profile.gender
    )
