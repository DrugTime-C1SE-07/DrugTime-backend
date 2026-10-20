from datetime import date, datetime
from uuid import UUID

from drugtime.modules.medication.application.profile_ports import (
    ConditionCatalog,
    HealthProfileAccess,
    PersonalProfiles,
    UserConditions,
)
from drugtime.modules.medication.domain.user_condition import HealthProfile, UserConditionView
from drugtime.shared.uow import UnitOfWork


def get_profile(
    uow: UnitOfWork,
    *,
    user_id: UUID,
    is_admin: bool,
    access: HealthProfileAccess,
    profiles: PersonalProfiles,
    conditions: UserConditions,
    catalog: ConditionCatalog,
) -> HealthProfile:
    access.authorize_read(uow, user_id, is_admin)
    profile = profiles.get(uow, user_id)
    links = conditions.list(uow, user_id)
    names = catalog.names(uow, [link.condition_id for link in links])
    return HealthProfile(
        profile.full_name,
        profile.date_of_birth,
        profile.gender,
        profile.email,
        [
            UserConditionView(
                link.id, link.condition_id, names[link.condition_id], link.subtype, link.stage
            )
            for link in links
        ],
    )


def update_profile(
    uow: UnitOfWork,
    *,
    user_id: UUID,
    is_admin: bool,
    access: HealthProfileAccess,
    profiles: PersonalProfiles,
    full_name: str,
    date_of_birth: date,
    gender: str,
    email: str | None = None,
    at: datetime,
) -> tuple[str | None, bool]:
    access.authorize_write(uow, user_id, is_admin)
    return profiles.update(
        uow,
        user_id,
        full_name=full_name,
        date_of_birth=date_of_birth,
        gender=gender,
        email=email,
        at=at,
    )
