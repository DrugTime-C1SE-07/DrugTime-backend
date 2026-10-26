"""Giao diện công khai của medication."""

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter

from drugtime.modules.medication.adapters.inbound.http import (
    patients_router,
    set_recorded_doses,
)
from drugtime.modules.medication.adapters.inbound.http import router as _medications_router
from drugtime.modules.medication.adapters.inbound.profile_http import router as _profile_router
from drugtime.modules.medication.adapters.outbound.other_modules import CatalogAdapter
from drugtime.modules.medication.adapters.outbound.sql_medication import SqlMedication
from drugtime.modules.medication.application.ports import RecordedDoses
from drugtime.modules.medication.domain.schedule import DoseOccurrence
from drugtime.shared.uow import UnitOfWork

__all__ = [
    "alert_context",
    "DoseOccurrence",
    "RecordedDoses",
    "configure",
    "eraser",
    "occurrences_between",
    "router",
    "schedule_ids_of",
    "schedule_owner",
]


# /medications và /patients/{id}/schedules (task 2.04), main.py include một router.
router = APIRouter()
router.include_router(_medications_router)
router.include_router(patients_router)
router.include_router(_profile_router)


def configure(*, recorded_doses: RecordedDoses) -> None:
    """Composition root nối port mà module khác hiện thực (task 2.04)."""
    set_recorded_doses(recorded_doses)


def alert_context(uow: UnitOfWork, schedule_id: int, patient_id: UUID) -> str | None:
    """Medication name for an occurrence owned by this patient; no guessed fallback."""
    medication_id = SqlMedication().alert_medication_id(uow, schedule_id, patient_id)
    if medication_id is None:
        return None
    # Lịch cũ vẫn cần tên thuốc đã soft-delete; đọc catalog qua adapter của module.
    medication = CatalogAdapter().get_medication(uow, medication_id, include_deleted=True)
    return None if medication is None else medication.name


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
