"""Giao diện công khai của medication."""

from datetime import datetime
from uuid import UUID

from drugtime.modules.medication.adapters.inbound.http import router
from drugtime.modules.medication.adapters.outbound.sql_medication import SqlMedication
from drugtime.modules.medication.domain.schedule import DoseOccurrence
from drugtime.shared.uow import UnitOfWork

__all__ = [
    "DoseOccurrence",
    "eraser",
    "occurrences_between",
    "router",
    "schedule_ids_of",
    "schedule_owner",
]


def schedule_owner(uow: UnitOfWork, schedule_id: int) -> UUID | None:
    return SqlMedication().schedule_owner(uow, schedule_id)


def schedule_ids_of(uow: UnitOfWork, user_id: UUID) -> list[int]:
    return SqlMedication().schedule_ids_of(uow, user_id)


def occurrences_between(uow: UnitOfWork, start: datetime, end: datetime) -> list[DoseOccurrence]:
    return SqlMedication().occurrences_between(uow, start, end)


class _Eraser:
    name = "medication"

    def erase_user(self, uow: UnitOfWork, user_id: UUID) -> None:
        SqlMedication().erase(uow, user_id)


eraser = _Eraser()
