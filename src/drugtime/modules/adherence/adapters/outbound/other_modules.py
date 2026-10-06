"""Adapter gọi module khác qua api.py (K16, K23, W07–W09)."""

from datetime import datetime
from uuid import UUID

from drugtime.modules.access import api as access
from drugtime.modules.identity import api as identity
from drugtime.modules.medication import api as medication
from drugtime.shared.uow import UnitOfWork


class AccessGuardAdapter:
    def authorize_adherence(
        self, uow: UnitOfWork, caller_id: UUID, caller_is_admin: bool, patient_id: UUID
    ) -> None:
        access.authorize(
            uow,
            caller_id=caller_id,
            caller_is_admin=caller_is_admin,
            patient_id=patient_id,
            scope=access.Scope.ADHERENCE,
        )

    def caregivers_of(self, uow: UnitOfWork, patient_id: UUID) -> list[UUID]:
        return access.authorized_caregivers(uow, patient_id)


class SchedulesAdapter:
    def owner(self, uow: UnitOfWork, schedule_id: int) -> UUID | None:
        return medication.schedule_owner(uow, schedule_id)

    def ids_of(self, uow: UnitOfWork, user_id: UUID) -> list[int]:
        return medication.schedule_ids_of(uow, user_id)

    def occurrences_between(self, uow: UnitOfWork, start: datetime, end: datetime) -> list:
        return medication.occurrences_between(uow, start, end)


class DeviceTokensAdapter:
    def android_tokens(self, uow: UnitOfWork, user_ids: list[UUID]) -> list[tuple[UUID, str]]:
        return identity.android_tokens(uow, user_ids)
