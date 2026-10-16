from fastapi import APIRouter, Depends, Query
from fastapi.security import HTTPBearer
from pydantic import BaseModel

from drugtime.modules.catalog.adapters.inbound.condition_schemas import (
    ConditionListResponse,
    ConditionResponse,
)
from drugtime.modules.catalog.adapters.outbound.sql_conditions import SqlConditions
from drugtime.modules.catalog.application.list_conditions import list_conditions
from drugtime.modules.identity import api as identity
from drugtime.shared.db import SqlUnitOfWork, get_uow

router = APIRouter(
    tags=["catalog"],
    dependencies=[
        Depends(HTTPBearer(auto_error=False, scheme_name="bearerAuth", bearerFormat="JWT"))
    ],
)


class ConditionError(BaseModel):
    detail: str


@router.get(
    "/conditions",
    response_model=ConditionListResponse,
    operation_id="listConditions",
    responses={401: {"model": ConditionError}, 500: {"model": ConditionError}},
)
def get_conditions(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user: identity.CurrentUser = Depends(identity.current_user),
    uow: SqlUnitOfWork = Depends(get_uow),
) -> ConditionListResponse:
    page = list_conditions(uow, SqlConditions(), limit=limit, offset=offset)
    return ConditionListResponse(
        items=[ConditionResponse.model_validate(c) for c in page.items],
        total=page.total,
        limit=limit,
        offset=offset,
    )
