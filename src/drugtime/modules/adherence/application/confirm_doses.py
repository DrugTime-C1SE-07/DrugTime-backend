from datetime import datetime
from uuid import UUID

from drugtime.modules.adherence.application.ports import AccessGuard, DoseLogs, Schedules
from drugtime.modules.adherence.domain.dose import (
    ClientUuidConflict,
    DoseConfirmation,
    DoseConfirmationBatchResult,
    DoseConfirmationError,
    DoseConfirmationItemError,
    DoseConfirmationResult,
    status_for_confirmation,
)
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
) -> DoseConfirmationBatchResult:
    """DK4. Mỗi item idempotent theo (schedule_id, scheduled_at) và client_uuid."""
    results: list[DoseConfirmationResult] = []
    for item in items:
        try:
            status = status_for_confirmation(item, now)
            owner_id = schedules.owner(uow, item.schedule_id)
            if owner_id is None:
                results.append(
                    _failed(item, "schedule_not_found", 404, "schedule_id was not found")
                )
                continue
            access.authorize_adherence(uow, caller_id, caller_is_admin, owner_id)
            persistence = dose_logs.upsert_confirmation(uow, item, status)
            record = persistence.record
            results.append(
                DoseConfirmationResult(
                    client_uuid=item.client_uuid,
                    schedule_id=item.schedule_id,
                    scheduled_at=record.scheduled_at,
                    result="synced",
                    dose_log_id=record.id,
                    dose_status=record.status,
                    adherence_counted=persistence.adherence_counted,
                    synced_at=record.synced_at,
                )
            )
        except DoseConfirmationError as exc:
            results.append(_failed(item, exc.code, 422, exc.detail))
        except ClientUuidConflict as exc:
            results.append(_failed(item, "client_uuid_conflict", 409, str(exc)))
        except Forbidden:
            results.append(_failed(item, "forbidden_schedule", 403, "schedule is forbidden"))
    return DoseConfirmationBatchResult(results)


def _failed(
    item: DoseConfirmation, code: str, http_status: int, detail: str
) -> DoseConfirmationResult:
    return DoseConfirmationResult(
        client_uuid=item.client_uuid,
        schedule_id=item.schedule_id,
        scheduled_at=item.scheduled_at,
        result="failed",
        error=DoseConfirmationItemError(code=code, http_status=http_status, detail=detail),
    )
