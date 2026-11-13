from collections.abc import Iterator
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.security import HTTPBearer
from pydantic import BaseModel
from sqlalchemy.exc import SQLAlchemyError

from drugtime.modules.consent.adapters.inbound.schemas import (
    Consent,
    ConsentGrantRequest,
    ConsentList,
    PendingDataDeletionRequest,
    PendingDataDeletionRequestPage,
    PendingDeletionQueueQuery,
)
from drugtime.modules.consent.adapters.outbound.sql_consent import SqlConsents, SqlDeletionRequests
from drugtime.modules.consent.application.manage_consents import (
    grant_consent,
    list_consents,
    withdraw_consent,
)
from drugtime.modules.consent.domain.purpose import Purpose
from drugtime.modules.identity import api as identity
from drugtime.shared.db import SqlUnitOfWork, get_uow, unit_of_work
from drugtime.shared.errors import ServiceUnavailable

router = APIRouter(tags=["consent"])


class ErrorDetail(BaseModel):
    detail: str


_UNAUTHORIZED = {401: {"model": ErrorDetail, "description": "Chưa xác thực"}}


# Chỉ thao tác trên consent của chính người gọi: không nhận user_id/patient_id, không có dữ
# liệu sức khỏe, nên không đi qua PEP và không ghi access_logs (chính chủ không ghi log).
@router.get(
    "/consents",
    response_model=ConsentList,
    responses=_UNAUTHORIZED,
    operation_id="listMyConsents",
)
def list_my_consents(
    uow: SqlUnitOfWork = Depends(get_uow),
    user: identity.CurrentUser = Depends(identity.current_user),
) -> ConsentList:
    states = list_consents(uow, user_id=user.id, store=SqlConsents())
    return ConsentList(items=[Consent.from_state(s) for s in states])


@router.post(
    "/consents",
    status_code=201,
    response_model=Consent,
    responses={
        200: {"model": Consent, "description": "Mục đích đã có consent hiệu lực"},
        **_UNAUTHORIZED,
        422: {"description": "ValidationError, hoặc ErrorDetail consent_document_outdated"},
    },
    operation_id="grantConsent",
)
def post_consent(
    body: ConsentGrantRequest,
    response: Response,
    uow: SqlUnitOfWork = Depends(get_uow),
    user: identity.CurrentUser = Depends(identity.current_user),
) -> Consent:
    state, created = grant_consent(
        uow,
        user_id=user.id,
        purpose=body.purpose,
        document_version=body.document_version,
        store=SqlConsents(),
    )
    response.status_code = 201 if created else 200
    return Consent.from_state(state)


@router.post(
    "/consents/{purpose}/withdraw",
    response_model=Consent,
    responses={
        **_UNAUTHORIZED,
        422: {
            "description": "ValidationError khi purpose không hợp lệ, "
            "hoặc ErrorDetail consent_not_withdrawable khi purpose là terms"
        },
    },
    operation_id="withdrawConsent",
)
def post_withdraw_consent(
    purpose: Purpose,
    uow: SqlUnitOfWork = Depends(get_uow),
    user: identity.CurrentUser = Depends(identity.current_user),
) -> Consent:
    state = withdraw_consent(uow, user_id=user.id, purpose=purpose, store=SqlConsents())
    return Consent.from_state(state)


def get_deletion_queue_uow() -> Iterator[SqlUnitOfWork]:
    try:
        with unit_of_work() as uow:
            yield uow
    except SQLAlchemyError as exc:
        raise ServiceUnavailable("service_unavailable") from exc


DeletionQueueUow = Annotated[SqlUnitOfWork, Depends(get_deletion_queue_uow, scope="function")]


def require_deletion_queue_admin(
    uow: DeletionQueueUow, authorization: str | None = Header(None)
) -> identity.CurrentUser:
    user = identity.current_user(authorization=authorization, uow=uow)
    return identity.require_admin(user)


async def validate_deletion_queue_input(request: Request) -> None:
    errors = [
        {
            "loc": ("query", key),
            "type": "value_error",
            "msg": "Query parameter must not be repeated",
        }
        for key in ("skip", "limit")
        if len(request.query_params.getlist(key)) > 1
    ]
    if await request.body():
        errors.append(
            {"loc": ("body",), "type": "extra_forbidden", "msg": "Request body is not allowed"}
        )
    if errors:
        raise RequestValidationError(errors)


@router.get(
    "/admin/deletion-requests",
    response_model=PendingDataDeletionRequestPage,
    responses={
        200: {
            "headers": {
                "Cache-Control": {
                    "required": True,
                    "schema": {"type": "string", "const": "no-store"},
                }
            }
        },
        **_UNAUTHORIZED,
        403: {"model": ErrorDetail, "description": "Chỉ Admin (`admin_only`)"},
        503: {"model": ErrorDetail, "description": "Không thể đọc hàng chờ"},
    },
    dependencies=[
        Depends(HTTPBearer(auto_error=False, scheme_name="bearerAuth", bearerFormat="JWT")),
        Depends(require_deletion_queue_admin),
        Depends(validate_deletion_queue_input),
    ],
    operation_id="listPendingDataDeletionRequests",
)
def list_pending_deletion_requests(
    response: Response, uow: DeletionQueueUow, query: Annotated[PendingDeletionQueueQuery, Query()]
) -> PendingDataDeletionRequestPage:
    records, total = SqlDeletionRequests().list_pending(uow, skip=query.skip, limit=query.limit)
    response.headers["Cache-Control"] = "no-store"
    return PendingDataDeletionRequestPage(
        items=[PendingDataDeletionRequest.from_record(record) for record in records], total=total
    )


# TODO: POST /deletion-requests and POST /admin/deletion-requests/{id}/approve
#       (approve: set da_duyet trong transaction, rồi job_queue.enqueue_erasure)
