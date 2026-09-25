from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel

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
    schedule_id: UUID
    scheduled_at: datetime
    taken_at: datetime


@router.post("/doses/batch", status_code=204)
def post_doses(
    items: list[DoseConfirmationIn],
    uow: SqlUnitOfWork = Depends(get_uow),
    user: identity.CurrentUser = Depends(identity.current_user),
) -> None:
    confirm_doses(
        uow,
        caller_id=user.id,
        caller_is_admin=user.is_admin,
        items=[DoseConfirmation(**i.model_dump()) for i in items],
        now=now(),
        access=AccessGuardAdapter(),
        schedules=SchedulesAdapter(),
        dose_logs=SqlDoseLogs(),
    )


# TODO: GET /patients/{patient_id}/adherence (DK1), GET /notifications (DK7)
