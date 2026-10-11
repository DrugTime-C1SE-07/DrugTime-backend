from uuid import UUID

from drugtime.modules.medication.application.get_medication import owner_or_404
from drugtime.modules.medication.application.ports import (
    AccessGuard,
    RecordedDoses,
    UserMedications,
)
from drugtime.modules.medication.domain.schedule_changes import close_all
from drugtime.modules.medication.domain.user_medication import NOT_FOUND
from drugtime.shared.errors import NotFound
from drugtime.shared.uow import UnitOfWork


def delete_medication(
    uow: UnitOfWork,
    *,
    caller_id: UUID,
    caller_is_admin: bool,
    user_medication_id: int,
    access: AccessGuard,
    meds: UserMedications,
    recorded: RecordedDoses,
) -> None:
    """Xoá mềm thuốc của chính người bệnh: đóng lịch mở theo mốc hiệu lực (sau liều xác nhận
    sớm nếu có, task 2.04), ngừng (nếu đang dùng) và đánh dấu xoá tại mốc `at`. dose_logs giữ
    nguyên."""
    owner = owner_or_404(uow, user_medication_id, meds)
    access.authorize_write(uow, caller_id, caller_is_admin, owner)
    state, at = meds.lock(uow, user_medication_id)
    if state.deleted:
        raise NotFound(NOT_FOUND)
    ids = [s.id for s in state.open_schedules]
    latest = recorded.latest_at_or_after(uow, ids, at) if ids else {}
    for schedule_id, ended_at in close_all(state, at, latest):
        meds.close_schedule(uow, schedule_id, ended_at, at)
    meds.stop(uow, user_medication_id, at)
    meds.mark_deleted(uow, user_medication_id, at)
