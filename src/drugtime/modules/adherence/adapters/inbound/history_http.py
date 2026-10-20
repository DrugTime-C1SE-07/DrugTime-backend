from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from fastapi.security import HTTPBearer

from drugtime.modules.adherence.adapters.inbound.history_schemas import (
    AdherenceError,
    AdherenceHistoryResponse,
    AdherenceRequestValidationError,
    QueryDate,
)
from drugtime.modules.adherence.adapters.outbound.other_modules import AccessGuardAdapter
from drugtime.modules.adherence.adapters.outbound.sql_adherence import SqlAdherenceHistory
from drugtime.modules.adherence.application.get_adherence_history import get_adherence_history
from drugtime.modules.adherence.domain.history import GroupBy
from drugtime.modules.identity import api as identity
from drugtime.shared.clock import now
from drugtime.shared.db import unit_of_work

router = APIRouter(
    dependencies=[
        Depends(HTTPBearer(auto_error=False, scheme_name="bearerAuth", bearerFormat="JWT"))
    ]
)
_ACCESS = AccessGuardAdapter()
_READER = SqlAdherenceHistory()
_HEADERS = {"Cache-Control": {"schema": {"type": "string", "const": "no-store"}}}
_RESPONSES = {code: {"model": AdherenceError, "headers": _HEADERS} for code in (401, 403, 500)}
_RESPONSES[422] = {
    "model": AdherenceError | AdherenceRequestValidationError,
    "headers": _HEADERS,
}
_RESPONSES[200] = {"headers": _HEADERS}


@router.get(
    "/adherence",
    response_model=AdherenceHistoryResponse,
    responses=_RESPONSES,
    operation_id="getAdherenceHistory",
    openapi_extra={"x-health-scope": "lich_su_tuan_thu", "x-health-audit-self": True},
)
def read_history(
    start: Annotated[QueryDate, Query(alias="from")] = None,
    end: Annotated[QueryDate, Query(alias="to")] = None,
    patient_id: UUID | None = None,
    group_by: GroupBy = GroupBy.DATE,
    user: identity.CurrentUser = Depends(identity.current_user),
):
    as_of = now()
    with unit_of_work() as uow:
        history = get_adherence_history(
            uow,
            caller_id=user.id,
            caller_is_admin=user.is_admin,
            patient_id=patient_id,
            start=start,
            end=end,
            group_by=group_by,
            as_of=as_of,
            access=_ACCESS,
            reader=_READER,
        )
        payload = AdherenceHistoryResponse.model_validate(history, from_attributes=True).model_dump(
            mode="json", by_alias=True
        )
        response = JSONResponse(payload, headers={"Cache-Control": "no-store"})
    return response
