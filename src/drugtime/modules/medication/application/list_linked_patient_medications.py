from dataclasses import dataclass
from uuid import UUID

from drugtime.modules.medication.application.get_medication import load_view
from drugtime.modules.medication.application.ports import AccessGuard, Catalog, UserMedications
from drugtime.modules.medication.domain import patient_medication_cursor as cursor_codec
from drugtime.modules.medication.domain.user_medication import UserMedicationView
from drugtime.shared.uow import UnitOfWork


@dataclass(frozen=True)
class PatientMedicationPage:
    items: list[UserMedicationView]
    next_cursor: str | None


def list_linked_patient_medications(
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
) -> PatientMedicationPage:
    access.authorize_read(uow, caller_id, caller_is_admin, patient_id)
    before = None if cursor is None else cursor_codec.decode(cursor, patient_id)
    ids = meds.active_ids_page(uow, patient_id, before, limit + 1)
    page = ids[:limit]
    return PatientMedicationPage(
        [load_view(uow, mid, meds, catalog) for mid in page],
        cursor_codec.encode(patient_id, page[-1]) if len(ids) > limit else None,
    )
