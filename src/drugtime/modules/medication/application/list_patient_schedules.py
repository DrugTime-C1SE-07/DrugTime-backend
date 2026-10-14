from dataclasses import dataclass
from uuid import UUID

from drugtime.modules.medication.application.ports import AccessGuard, Catalog, UserMedications
from drugtime.modules.medication.domain import schedule_cursor
from drugtime.modules.medication.domain.user_medication import (
    MedicationInfo,
    PatientScheduleView,
)
from drugtime.shared.uow import UnitOfWork


@dataclass(frozen=True)
class PatientSchedulePage:
    items: list[PatientScheduleView]
    next_cursor: str | None


def list_patient_schedules(
    uow: UnitOfWork,
    *,
    caller_id: UUID,
    caller_is_admin: bool,
    patient_id: UUID,
    limit: int,
    cursor: str | None,
    access: AccessGuard,
    catalog: Catalog,
    meds: UserMedications,
) -> PatientSchedulePage:
    """Một trang lịch của người bệnh (QD-18). Kiểm quyền trước khi đọc hay giải mã gì."""
    access.authorize_read(uow, caller_id, caller_is_admin, patient_id)
    after = 0 if cursor is None else schedule_cursor.decode(cursor, patient_id)
    rows = meds.patient_schedules(uow, patient_id, after, limit + 1)
    page, more = rows[:limit], len(rows) > limit
    infos: dict[int, MedicationInfo] = {}
    for r in page:
        if r.medication_id not in infos:
            # Thuốc người bệnh đang dùng vẫn hiển thị khi danh mục đã xoá mềm.
            info = catalog.get_medication(uow, r.medication_id, include_deleted=True)
            if info is None:
                raise LookupError(f"catalog medication {r.medication_id} missing")
            infos[r.medication_id] = info
    return PatientSchedulePage(
        items=[PatientScheduleView(r, infos[r.medication_id]) for r in page],
        next_cursor=schedule_cursor.encode(patient_id, page[-1].id) if more else None,
    )
