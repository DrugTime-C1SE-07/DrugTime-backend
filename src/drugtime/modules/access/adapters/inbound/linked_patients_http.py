from collections.abc import Callable
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from fastapi.security import HTTPBearer
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.exc import SQLAlchemyError

from drugtime.modules.access.adapters.outbound.facts import ModuleFactsReader
from drugtime.modules.access.adapters.outbound.linked_patients_gateway import (
    LinkedPatientCandidates,
    LinkedPatientNames,
    LinkedPatientRequestAudit,
)
from drugtime.modules.access.adapters.outbound.sql_access_log import SqlAccessLog
from drugtime.modules.access.application.list_linked_patients import list_linked_patients
from drugtime.modules.access.domain.rules import Scope
from drugtime.modules.identity import api as identity
from drugtime.shared.db import unit_of_work
from drugtime.shared.errors import ServiceUnavailable


class PatientListRoute(APIRoute):
    def get_route_handler(self) -> Callable:
        handler = super().get_route_handler()

        async def guarded(request: Request):
            try:
                return await handler(request)
            except SQLAlchemyError:
                # Covers authentication/dependency SQL as well as read/audit/commit SQL.
                # Do not log exception text or SQL parameters (PII).
                raise ServiceUnavailable("service_unavailable") from None

        return guarded


router = APIRouter(
    tags=["family"],
    route_class=PatientListRoute,
    dependencies=[Depends(HTTPBearer(auto_error=False, scheme_name="bearerAuth"))],
)


class LinkedPatient(BaseModel):
    model_config = ConfigDict(extra="forbid")

    patient_id: UUID
    patient_full_name: Annotated[str, Field(min_length=1)] | None


class LinkedPatientList(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[LinkedPatient]


class ErrorDetail(BaseModel):
    detail: str


class PatientListValidationErrorItem(BaseModel):
    loc: list[str | int]
    msg: str
    type: str


class PatientListValidationError(BaseModel):
    detail: list[PatientListValidationErrorItem]


_HEADERS = {"Cache-Control": {"schema": {"type": "string", "const": "no-store"}}}
_RESPONSES = {code: {"model": ErrorDetail, "headers": _HEADERS} for code in (401, 403, 503)}
_RESPONSES[200] = {"headers": _HEADERS}
_RESPONSES[422] = {"model": PatientListValidationError, "headers": _HEADERS}


async def validate_input(
    request: Request,
    _user: Annotated[identity.CurrentUser, Depends(identity.current_user)],
) -> None:
    errors = [
        {"type": "extra_forbidden", "loc": ("query", key), "msg": "Extra inputs are not permitted"}
        for key, _ in request.query_params.multi_items()
    ]
    if await request.body():
        errors.append(
            {"type": "extra_forbidden", "loc": ("body",), "msg": "Extra inputs are not permitted"}
        )
    if errors:
        raise RequestValidationError(errors)


@router.get(
    "/family/patients",
    response_model=LinkedPatientList,
    responses=_RESPONSES,
    operation_id="listMyLinkedPatients",
    openapi_extra={"x-health-scope": Scope.LINKED_PATIENTS.value, "x-health-audit-self": False},
)
def get_linked_patients(
    user: Annotated[identity.CurrentUser, Depends(identity.current_user)],
    validated: Annotated[None, Depends(validate_input)],
) -> JSONResponse:
    with unit_of_work() as uow:
        patients = list_linked_patients(
            uow,
            caller_id=user.id,
            caller_is_admin=user.is_admin,
            candidates=LinkedPatientCandidates(),
            facts=ModuleFactsReader(),
            access_log=SqlAccessLog(),
            names=LinkedPatientNames(),
            request_audit=LinkedPatientRequestAudit(),
        )
        payload = LinkedPatientList(
            items=[LinkedPatient.model_validate(p, from_attributes=True) for p in patients]
        ).model_dump(mode="json")
        response = JSONResponse(payload, headers={"Cache-Control": "no-store"})
    # unit_of_work must commit successfully before the response can leave the handler.
    return response
