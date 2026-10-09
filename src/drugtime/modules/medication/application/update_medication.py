from datetime import datetime
from uuid import UUID

from drugtime.modules.medication.application.get_medication import load_view, owner_or_404
from drugtime.modules.medication.application.ports import (
    AccessGuard,
    Catalog,
    RecordedDoses,
    UserMedications,
)
from drugtime.modules.medication.domain.schedule_changes import (
    close_all,
    pick_reactivation,
    plan_reactivation,
    replace_all,
)
from drugtime.modules.medication.domain.user_medication import (
    NOT_FOUND,
    RULE_VIOLATION,
    DosingMode,
    MedicationChanges,
    MedicationState,
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
    recorded: RecordedDoses,
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
    # Mọi đường đóng/mở lịch theo mốc hiệu lực: lịch có liều xác nhận sớm đóng sau liều đó, lịch
    # mới cùng giờ không bắt đầu trước mốc ấy (QD-16, task 2.04).
    ids = [s.id for s in state.open_schedules]
    latest = recorded.latest_at_or_after(uow, ids, at) if ids and plan.close_open_schedules else {}
    if plan.new_intake_times:
        # Thay toàn bộ lịch: đổi giờ, đổi ngày, chuyển sang theo giờ.
        write = replace_all(
            state,
            at,
            latest,
            plan.new_intake_times,
            plan.new_days_of_week,
            plan.new_reminders or (True,) * len(plan.new_intake_times),
        )
        for schedule_id, ended_at in write.close:
            meds.close_schedule(uow, schedule_id, ended_at)
        meds.add_schedules(uow, user_medication_id, write.insert)
    elif plan.close_open_schedules:
        # Ngừng thuốc, chuyển sang khi cần: đóng, không có lịch thay thế. Ngừng đánh dấu lịch để
        # dùng lại mở đúng các lịch này (R3).
        stopped_at = at if plan.stop else None
        for schedule_id, ended_at in close_all(state, at, latest):
            meds.close_schedule(uow, schedule_id, ended_at, stopped_at)
    if plan.stop:
        meds.stop(uow, user_medication_id, at)
    if plan.reactivate and state.ended_at is not None:
        _reactivate(uow, user_medication_id, state, at, state.ended_at, meds)
    return load_view(uow, user_medication_id, meds, catalog)


def _reactivate(
    uow: UnitOfWork,
    user_medication_id: int,
    state: MedicationState,
    at: datetime,
    stopped_at: datetime,
    meds: UserMedications,
) -> None:
    """Dùng lại thuốc đã ngừng: mở lại các lịch mang dấu đóng bởi lần ngừng gần nhất, đặt
    doses_per_day theo số lịch mở lại, rồi bỏ ended_at của thuốc. Thuốc khi cần không có lịch:
    không mở lịch nào (R2 của review)."""
    if state.dosing_mode is DosingMode.AS_NEEDED:
        meds.resume(uow, user_medication_id)
        return
    picked = pick_reactivation(meds.closed_by_stop(uow, user_medication_id, stopped_at))
    if not picked:
        # Không còn lịch của lần ngừng; transaction rollback nên không ghi gì.
        raise DomainError(RULE_VIOLATION)
    meds.add_schedules(uow, user_medication_id, plan_reactivation(state, at, picked).insert)
    meds.update_fields(uow, user_medication_id, {"doses_per_day": len(picked)})
    meds.resume(uow, user_medication_id)
