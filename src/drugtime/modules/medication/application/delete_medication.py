from uuid import UUID

from drugtime.modules.medication.application.get_medication import owner_or_404
from drugtime.modules.medication.application.ports import AccessGuard, UserMedications
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
) -> None:
    """Xoá mềm thuốc của chính người bệnh: đóng lịch mở, ngừng (nếu đang dùng), đánh dấu xoá,
    cùng một mốc `at`. dose_logs giữ nguyên."""
    owner = owner_or_404(uow, user_medication_id, meds)
    access.authorize_write(uow, caller_id, caller_is_admin, owner)
    state, at = meds.lock(uow, user_medication_id)
    if state.deleted:
        raise NotFound(NOT_FOUND)
    meds.close_open_schedules(uow, user_medication_id, at)
    meds.stop(uow, user_medication_id, at)
    meds.mark_deleted(uow, user_medication_id, at)
