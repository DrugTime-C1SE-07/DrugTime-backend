from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.security import HTTPBearer
from pydantic import BaseModel, ConfigDict, Field

from drugtime.modules.consent.adapters.outbound.sql_deletion_creation import SqlDeletionCreation
from drugtime.modules.consent.application.create_deletion_request import DeletionCreation
from drugtime.modules.identity import api as identity
from drugtime.shared.clock import now
from drugtime.shared.db import unit_of_work

router = APIRouter(
    prefix="/data-deletion-requests",
    tags=["consent"],
    dependencies=[Depends(HTTPBearer(auto_error=False, scheme_name="bearerAuth"))],
)


class DeletionOtpChallenge(BaseModel):
    challenge_id: UUID
    expires_at: datetime


class CreateDeletionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    challenge_id: UUID
    otp: str = Field(min_length=1, max_length=128, json_schema_extra={"writeOnly": True})


class ConfirmDeletionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    challenge_id: UUID


class PendingDeletionRequest(BaseModel):
    status: Literal["cho_xoa"]
    requested_at: datetime
    scheduled_deletion_at: datetime


class ErrorDetail(BaseModel):
    detail: str


class DeletionValidationErrorItem(BaseModel):
    loc: list[str | int]
    msg: str
    type: str


class DeletionValidationError(BaseModel):
    detail: list[DeletionValidationErrorItem]


_NO_STORE = {"headers": {"Cache-Control": {"schema": {"type": "string", "const": "no-store"}}}}
_ERRORS = {code: {"model": ErrorDetail, **_NO_STORE} for code in (401, 403, 409, 429, 503)}
_ERRORS[429] = {
    "model": ErrorDetail,
    "headers": {
        **_NO_STORE["headers"],
        "Retry-After": {"schema": {"type": "integer", "minimum": 1}},
    },
}
_OTP_INVALID = {
    "model": ErrorDetail | DeletionValidationError,
    "headers": {
        **_NO_STORE["headers"],
        "X-OTP-Attempts-Remaining": {"schema": {"type": "integer", "minimum": 0, "maximum": 5}},
        "Retry-After": {"schema": {"type": "integer", "minimum": 1}},
    },
}


def get_deletion_creation() -> DeletionCreation:
    return DeletionCreation(
        transactions=unit_of_work,
        store=SqlDeletionCreation(),
        verified_email=identity.verified_email,
        send_otp=lambda email: identity.request_otp(phone=None, email=email, create_user=False),
        verify_otp=lambda email, otp: identity.verify_auth_otp(email=email, token=otp),
        clock=now,
    )


def _reject_query(request: Request) -> None:
    if request.query_params:
        raise RequestValidationError(
            [{"loc": ["query"], "msg": "Unexpected query parameters", "type": "extra_forbidden"}]
        )


async def _reject_body(request: Request) -> None:
    if await request.body():
        raise RequestValidationError(
            [{"loc": ["body"], "msg": "Unexpected request body", "type": "extra_forbidden"}]
        )


@router.post(
    "/otp",
    status_code=201,
    operation_id="requestAccountDeletionOtp",
    responses={201: _NO_STORE, **_ERRORS, 422: {"model": DeletionValidationError, **_NO_STORE}},
    dependencies=[Depends(_reject_query), Depends(_reject_body)],
)
def request_deletion_otp(
    user: identity.CurrentUser = Depends(identity.current_mobile_user),
    service: DeletionCreation = Depends(get_deletion_creation),
) -> DeletionOtpChallenge:
    challenge, expires = service.issue(user.id)
    return DeletionOtpChallenge(challenge_id=challenge, expires_at=expires)


@router.post(
    "",
    status_code=201,
    operation_id="createAccountDeletionRequest",
    responses={
        200: {"model": PendingDeletionRequest, **_NO_STORE},
        201: _NO_STORE,
        **_ERRORS,
        422: _OTP_INVALID,
    },
    dependencies=[Depends(_reject_query)],
)
def create_deletion_request(
    body: ConfirmDeletionRequest,
    response: Response,
    user: identity.CurrentUser = Depends(identity.current_mobile_user),
    service: DeletionCreation = Depends(get_deletion_creation),
) -> PendingDeletionRequest:
    pending, created = service.confirm(user.id, body.challenge_id)
    response.status_code = 201 if created else 200
    assert pending.scheduled_deletion_at is not None
    return PendingDeletionRequest(
        status="cho_xoa",
        requested_at=pending.requested_at.astimezone(UTC),
        scheduled_deletion_at=pending.scheduled_deletion_at.astimezone(UTC),
    )


@router.post(
    "/otp/verify",
    status_code=204,
    operation_id="verifyAccountDeletionOtp",
    responses={
        204: _NO_STORE,
        **_ERRORS,
        422: _OTP_INVALID,
    },
    dependencies=[Depends(_reject_query)],
)
def verify_deletion_otp(
    body: CreateDeletionRequest,
    user: identity.CurrentUser = Depends(identity.current_mobile_user),
    service: DeletionCreation = Depends(get_deletion_creation),
) -> Response:
    service.verify(user.id, body.challenge_id, body.otp)
    return Response(status_code=204)


@router.get(
    "/current",
    operation_id="getCurrentAccountDeletionRequest",
    responses={200: _NO_STORE, **_ERRORS, 422: {"model": DeletionValidationError, **_NO_STORE}},
    dependencies=[Depends(_reject_query), Depends(_reject_body)],
)
def current_deletion_request(
    user: identity.CurrentUser = Depends(identity.current_mobile_user),
    service: DeletionCreation = Depends(get_deletion_creation),
) -> PendingDeletionRequest | None:
    pending = service.current(user.id)
    if pending is None:
        return None
    if pending.scheduled_deletion_at is None:
        from drugtime.shared.errors import Conflict

        raise Conflict("deletion_request_not_cancellable")
    return PendingDeletionRequest(
        status="cho_xoa",
        requested_at=pending.requested_at,
        scheduled_deletion_at=pending.scheduled_deletion_at,
    )


@router.post(
    "/current/cancel",
    status_code=204,
    operation_id="cancelAccountDeletionRequest",
    responses={204: _NO_STORE, **_ERRORS, 422: {"model": DeletionValidationError, **_NO_STORE}},
    dependencies=[Depends(_reject_query), Depends(_reject_body)],
)
def cancel_deletion_request(
    user: identity.CurrentUser = Depends(identity.current_mobile_user),
    service: DeletionCreation = Depends(get_deletion_creation),
) -> Response:
    service.cancel(user.id)
    return Response(status_code=204)
