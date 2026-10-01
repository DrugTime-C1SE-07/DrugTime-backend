from uuid import UUID

from drugtime.modules.medication.application.ports import AccessGuard, Catalog, UserMedications
from drugtime.modules.medication.domain.user_medication import NOT_FOUND, UserMedicationView
from drugtime.shared.errors import NotFound
from drugtime.shared.uow import UnitOfWork


def load_view(
    uow: UnitOfWork, user_medication_id: int, meds: UserMedications, catalog: Catalog
) -> UserMedicationView:
    record = meds.read(uow, user_medication_id)
    # Thuốc người bệnh đang dùng vẫn hiển thị khi danh mục đã xóa mềm.
    info = catalog.get_medication(uow, record.medication_id, include_deleted=True)
    if info is None:
        raise LookupError(f"catalog medication {record.medication_id} missing")
    return UserMedicationView(record, info)


def owner_or_404(uow: UnitOfWork, user_medication_id: int, meds: UserMedications) -> UUID:
    owner = meds.owner_of(uow, user_medication_id)
    if owner is None:
        raise NotFound(NOT_FOUND)
    return owner


def get_medication(
    uow: UnitOfWork,
    *,
    caller_id: UUID,
    caller_is_admin: bool,
    user_medication_id: int,
    access: AccessGuard,
    catalog: Catalog,
    meds: UserMedications,
) -> UserMedicationView:
    owner = owner_or_404(uow, user_medication_id, meds)
    access.authorize_read(uow, caller_id, caller_is_admin, owner)
    return load_view(uow, user_medication_id, meds, catalog)
