from uuid import UUID

from drugtime.modules.medication.application.get_medication import load_view
from drugtime.modules.medication.application.ports import AccessGuard, Catalog, UserMedications
from drugtime.modules.medication.domain.user_medication import (
    CATALOG_NOT_FOUND,
    NOT_FOUND,
    DosingMode,
    NewMedication,
    UserMedicationView,
    validate_new,
)
from drugtime.shared.errors import DomainError, NotFound
from drugtime.shared.uow import UnitOfWork


def create_medication(
    uow: UnitOfWork,
    *,
    caller_id: UUID,
    caller_is_admin: bool,
    cmd: NewMedication,
    access: AccessGuard,
    catalog: Catalog,
    meds: UserMedications,
) -> tuple[UserMedicationView, bool]:
    """Thêm thuốc cho chính người gọi. Trả (thuốc, True nếu vừa tạo).

    Gửi lại cùng client_uuid trả thuốc đã có trước khi xét quy tắc và danh mục, để
    lần gửi lại luôn nhận đúng thuốc cũ. Thuốc đó đã bị xoá thì 404, không tạo mới."""
    access.authorize_write(uow, caller_id, caller_is_admin, caller_id)
    existing = meds.find_by_client_uuid(uow, caller_id, cmd.client_uuid)
    if existing is not None:
        return _replay(uow, existing, meds, catalog), False

    cmd = validate_new(cmd)
    info = catalog.get_medication(uow, cmd.medication_id)
    if info is None:
        raise DomainError(CATALOG_NOT_FOUND)

    prescription_id = meds.default_prescription(uow, caller_id)
    new_id = meds.insert(uow, caller_id, prescription_id, cmd, info.has_active_ingredients)
    if new_id is None:
        # Request trùng chạy song song đã commit trước: trả thuốc của request đó.
        raced = meds.find_by_client_uuid(uow, caller_id, cmd.client_uuid)
        if raced is None:
            raise LookupError("client_uuid conflict without existing row")
        return _replay(uow, raced, meds, catalog), False
    if cmd.dosing_mode is DosingMode.SCHEDULED:
        meds.insert_schedules(uow, new_id, cmd.intake_times or (), cmd.days_of_week or ())
    return load_view(uow, new_id, meds, catalog), True


def _replay(
    uow: UnitOfWork, found: tuple[int, bool], meds: UserMedications, catalog: Catalog
) -> UserMedicationView:
    user_medication_id, deleted = found
    if deleted:
        raise NotFound(NOT_FOUND)
    return load_view(uow, user_medication_id, meds, catalog)
