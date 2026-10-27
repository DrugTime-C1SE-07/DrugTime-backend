from uuid import UUID

from drugtime.modules.adherence.application.ports import (
    DoseLogs,
    Notifications,
    PendingVerifications,
    Schedules,
    SyncCheckpoints,
)


def erase_user(
    uow,
    user_id: UUID,
    *,
    schedules: Schedules,
    dose_logs: DoseLogs,
    notifications: Notifications,
    checkpoints: SyncCheckpoints,
    pending: PendingVerifications,
) -> None:
    # Hàng chờ xác minh tham chiếu medication_schedules, nên xóa trước khi medication xóa lịch.
    pending.erase_for_patient(uow, user_id)
    checkpoints.erase_for_user(uow, user_id)
    dose_logs.erase_for_schedules(uow, schedules.ids_of(uow, user_id))
    notifications.erase_for_user(uow, user_id)
