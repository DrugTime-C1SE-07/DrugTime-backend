from uuid import UUID

from drugtime.modules.medication.application.get_medication import load_view
from drugtime.modules.medication.application.ports import AccessGuard, Catalog, UserMedications
from drugtime.modules.medication.domain.user_medication import UserMedicationView
from drugtime.shared.uow import UnitOfWork


def list_medications(
    uow: UnitOfWork,
    *,
    caller_id: UUID,
    caller_is_admin: bool,
    access: AccessGuard,
    catalog: Catalog,
    meds: UserMedications,
) -> list[UserMedicationView]:
    """Thuốc chưa xoá của chính người gọi, id giảm dần. Kiểm quyền trước khi đọc dữ liệu."""
    access.authorize_read(uow, caller_id, caller_is_admin, caller_id)
    return [load_view(uow, i, meds, catalog) for i in meds.ids_of(uow, caller_id)]
