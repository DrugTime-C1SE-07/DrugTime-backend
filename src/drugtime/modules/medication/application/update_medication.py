from uuid import UUID

from drugtime.modules.medication.application.get_medication import load_view, owner_or_404
from drugtime.modules.medication.application.ports import AccessGuard, Catalog, UserMedications
from drugtime.modules.medication.domain.user_medication import (
    MedicationChanges,
    UserMedicationView,
    plan_update,
)
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
    """Sửa hoặc ngừng thuốc; chỉ chính người bệnh. Mọi thay đổi trong transaction của request."""
    owner = owner_or_404(uow, user_medication_id, meds)
    access.authorize_write(uow, caller_id, caller_is_admin, owner)
    state, at = meds.lock(uow, user_medication_id)
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
    return load_view(uow, user_medication_id, meds, catalog)
