from uuid import UUID

from drugtime.modules.medication.application.get_medication import load_view, owner_or_404
from drugtime.modules.medication.application.ports import AccessGuard, Catalog, UserMedications
from drugtime.modules.medication.domain.user_medication import (
    NOT_FOUND,
    RULE_VIOLATION,
    DosingMode,
    MedicationChanges,
    UserMedicationView,
    plan_update,
)
from drugtime.shared.errors import DomainError, NotFound
from drugtime.shared.uow import UnitOfWork


def update_medication(
    uow: UnitOfWork,
    *,
    caller_id: UUID,
    caller_is_admin: bool,
    user_medication_id: int,
    changes: MedicationChanges,
    access: AccessGuard,
    catalog: Catalog,
    meds: UserMedications,
) -> UserMedicationView:
    """Sửa, ngừng hoặc dùng lại thuốc; chỉ chính người bệnh. Mọi thay đổi trong transaction
    của request."""
    owner = owner_or_404(uow, user_medication_id, meds)
    access.authorize_write(uow, caller_id, caller_is_admin, owner)
    state, at = meds.lock(uow, user_medication_id)
    if state.deleted:
        # Request khác xoá thuốc giữa owner_or_404 và lúc có khóa.
        raise NotFound(NOT_FOUND)
    plan = plan_update(state, changes)
    if plan.fields:
        meds.update_fields(uow, user_medication_id, plan.fields)
    if plan.close_open_schedules:
        meds.close_open_schedules(uow, user_medication_id, at)
    if plan.new_intake_times:
        meds.insert_schedules(
            uow, user_medication_id, plan.new_intake_times, plan.new_days_of_week, at
        )
    if plan.stop:
        meds.stop(uow, user_medication_id, at)
    if plan.reactivate:
        reopened = meds.reactivate(uow, user_medication_id, at)
        if state.dosing_mode is DosingMode.SCHEDULED and reopened == 0:
            # Dữ liệu cũ không còn lịch của lần ngừng; transaction rollback nên không ghi gì.
            raise DomainError(RULE_VIOLATION)
    return load_view(uow, user_medication_id, meds, catalog)
