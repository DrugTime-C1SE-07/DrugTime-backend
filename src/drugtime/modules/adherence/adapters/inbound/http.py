from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Body, Depends
from pydantic import BaseModel, ConfigDict

from drugtime.modules.adherence.adapters.outbound.other_modules import (
    AccessGuardAdapter,
    SchedulesAdapter,
)
from drugtime.modules.adherence.adapters.outbound.sql_adherence import SqlDoseLogs
from drugtime.modules.adherence.application.confirm_doses import confirm_doses
from drugtime.modules.adherence.domain.dose import DoseConfirmation
from drugtime.modules.identity import api as identity
from drugtime.shared.clock import now
from drugtime.shared.db import SqlUnitOfWork, get_uow

router = APIRouter(tags=["adherence"])


class DoseConfirmationIn(BaseModel):
    client_uuid: UUID
    schedule_id: int
    scheduled_at: datetime
    taken_at: datetime


class DoseConfirmationItemErrorOut(BaseModel):
    code: str
    http_status: int
    detail: str


class DoseConfirmationResultOut(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    client_uuid: UUID
    schedule_id: int
    scheduled_at: datetime
    result: str
    dose_log_id: int | None = None
    dose_status: str | None = None
    adherence_counted: bool | None = None
    synced_at: datetime | None = None
    error: DoseConfirmationItemErrorOut | None = None


class DoseConfirmationSummaryOut(BaseModel):
    total: int
    synced: int
    failed: int


class DoseConfirmationBatchOut(BaseModel):
    items: list[DoseConfirmationResultOut]
    summary: DoseConfirmationSummaryOut


@router.post(
    "/doses/batch",
    response_model=DoseConfirmationBatchOut,
    response_model_exclude_none=True,
)
def post_doses(
    items: Annotated[list[DoseConfirmationIn], Body(min_length=1, max_length=50)],
    uow: SqlUnitOfWork = Depends(get_uow),
    user: identity.CurrentUser = Depends(identity.current_user),
) -> DoseConfirmationBatchOut:
    result = confirm_doses(
        uow,
        caller_id=user.id,
        caller_is_admin=user.is_admin,
        items=[DoseConfirmation(**i.model_dump()) for i in items],
        now=now(),
        access=AccessGuardAdapter(),
        schedules=SchedulesAdapter(),
        dose_logs=SqlDoseLogs(),
    )
    return DoseConfirmationBatchOut(
        items=[
            DoseConfirmationResultOut(
                client_uuid=item.client_uuid,
                schedule_id=item.schedule_id,
                scheduled_at=item.scheduled_at,
                result=item.result,
                dose_log_id=item.dose_log_id,
                dose_status=item.dose_status.value if item.dose_status is not None else None,
                adherence_counted=item.adherence_counted,
                synced_at=item.synced_at,
                error=(
                    None
                    if item.error is None
                    else DoseConfirmationItemErrorOut(
                        code=item.error.code,
                        http_status=item.error.http_status,
                        detail=item.error.detail,
                    )
                ),
            )
            for item in result.items
        ],
        summary=DoseConfirmationSummaryOut(
            total=result.total,
            synced=result.synced,
            failed=result.failed,
        ),
    )


# TODO: GET /patients/{patient_id}/adherence (DK1), GET /notifications (DK7)
