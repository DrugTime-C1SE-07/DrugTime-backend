from uuid import UUID

from drugtime.modules.adherence.application.ports import DoseLogs, Notifications, Schedules


def erase_user(
    uow, user_id: UUID, *, schedules: Schedules, dose_logs: DoseLogs, notifications: Notifications
) -> None:
    dose_logs.erase_for_schedules(uow, schedules.ids_of(uow, user_id))
    notifications.erase_for_user(uow, user_id)
