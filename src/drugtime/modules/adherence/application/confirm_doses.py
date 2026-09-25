from datetime import datetime
from uuid import UUID

from drugtime.modules.adherence.application.ports import AccessGuard, DoseLogs, Schedules
from drugtime.modules.adherence.domain.dose import DoseConfirmation, validate_confirmation
from drugtime.shared.errors import Forbidden
from drugtime.shared.uow import UnitOfWork


def confirm_doses(
    uow: UnitOfWork,
    *,
    caller_id: UUID,
    caller_is_admin: bool,
    items: list[DoseConfirmation],
    now: datetime,
    access: AccessGuard,
    schedules: Schedules,
    dose_logs: DoseLogs,
) -> None:
    """DK4. Mỗi item idempotent theo (schedule_id, scheduled_at) và client_uuid."""
    access.authorize_adherence(uow, caller_id, caller_is_admin, caller_id)  # self, health_data
    for item in items:
        validate_confirmation(item, now)
        if schedules.owner(uow, item.schedule_id) != caller_id:
            raise Forbidden("Lịch không thuộc về người dùng")
        dose_logs.upsert_confirmation(uow, item)
