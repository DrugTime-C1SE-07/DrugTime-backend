"""Thêm, sửa, hủy từng lịch của thuốc (task 2.04). Chỉ chính người bệnh; mọi thay đổi trong
transaction của request, dưới khóa dòng thuốc."""

from collections.abc import Callable
from datetime import datetime, time
from uuid import UUID

from drugtime.modules.medication.application.get_medication import load_view, owner_or_404
from drugtime.modules.medication.application.ports import (
    AccessGuard,
    Catalog,
    RecordedDoses,
    UserMedications,
)
from drugtime.modules.medication.domain.schedule_changes import (
    ScheduleWrite,
    plan_add,
    plan_edit,
    plan_remove,
)
from drugtime.modules.medication.domain.user_medication import (
    NOT_FOUND,
    MedicationState,
    UserMedicationView,
)
from drugtime.shared.errors import NotFound
from drugtime.shared.uow import UnitOfWork

Planner = Callable[[MedicationState, datetime, dict[int, datetime]], ScheduleWrite]


def _apply(
    uow: UnitOfWork,
    *,
    caller_id: UUID,
    caller_is_admin: bool,
    user_medication_id: int,
    planner: Planner,
    access: AccessGuard,
    catalog: Catalog,
    meds: UserMedications,
    recorded: RecordedDoses,
) -> UserMedicationView:
    owner = owner_or_404(uow, user_medication_id, meds)
    access.authorize_write(uow, caller_id, caller_is_admin, owner)
    state, at = meds.lock(uow, user_medication_id)
    if state.deleted:
        # Request khác xoá thuốc giữa owner_or_404 và lúc có khóa.
        raise NotFound(NOT_FOUND)
    ids = [s.id for s in state.open_schedules]
    latest = recorded.latest_at_or_after(uow, ids, at) if ids else {}
    write = planner(state, at, latest)
    for schedule_id, ended_at in write.close:
        meds.close_schedule(uow, schedule_id, ended_at)
    meds.add_schedules(uow, user_medication_id, write.insert)
    if write.doses_per_day is not None:
        meds.update_fields(uow, user_medication_id, {"doses_per_day": write.doses_per_day})
    return load_view(uow, user_medication_id, meds, catalog)


def add_schedule(
    uow: UnitOfWork,
    *,
    caller_id: UUID,
    caller_is_admin: bool,
    user_medication_id: int,
    intake_time: time,
    reminder_enabled: bool,
    access: AccessGuard,
    catalog: Catalog,
    meds: UserMedications,
    recorded: RecordedDoses,
) -> UserMedicationView:
    return _apply(
        uow,
        caller_id=caller_id,
        caller_is_admin=caller_is_admin,
        user_medication_id=user_medication_id,
        planner=lambda state, at, _latest: plan_add(state, at, intake_time, reminder_enabled),
        access=access,
        catalog=catalog,
        meds=meds,
        recorded=recorded,
    )


def update_schedule(
    uow: UnitOfWork,
    *,
    caller_id: UUID,
    caller_is_admin: bool,
    user_medication_id: int,
    schedule_id: int,
    intake_time: time | None,
    reminder_enabled: bool | None,
    access: AccessGuard,
    catalog: Catalog,
    meds: UserMedications,
    recorded: RecordedDoses,
) -> UserMedicationView:
    """None = field không gửi."""
    return _apply(
        uow,
        caller_id=caller_id,
        caller_is_admin=caller_is_admin,
        user_medication_id=user_medication_id,
        planner=lambda state, at, latest: plan_edit(
            state,
            at,
            schedule_id,
            latest,
            intake_time=intake_time,
            reminder_enabled=reminder_enabled,
        ),
        access=access,
        catalog=catalog,
        meds=meds,
        recorded=recorded,
    )


def remove_schedule(
    uow: UnitOfWork,
    *,
    caller_id: UUID,
    caller_is_admin: bool,
    user_medication_id: int,
    schedule_id: int,
    access: AccessGuard,
    catalog: Catalog,
    meds: UserMedications,
    recorded: RecordedDoses,
) -> UserMedicationView:
    return _apply(
        uow,
        caller_id=caller_id,
        caller_is_admin=caller_is_admin,
        user_medication_id=user_medication_id,
        planner=lambda state, at, latest: plan_remove(state, at, schedule_id, latest),
        access=access,
        catalog=catalog,
        meds=meds,
        recorded=recorded,
    )
