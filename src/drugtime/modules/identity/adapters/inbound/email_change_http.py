from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.security import HTTPBearer
from pydantic import BaseModel, ConfigDict, Field

from drugtime.modules.identity.adapters.inbound.dependencies import current_mobile_user
from drugtime.modules.identity.adapters.outbound.email_change_otp import send_email_change_otp
from drugtime.modules.identity.adapters.outbound.sql_email_change import (
    SqlEmailChange,
    account_lock,
)
from drugtime.modules.identity.adapters.outbound.supabase_auth import SupabaseAuth
from drugtime.modules.identity.application.email_change import EmailChange
from drugtime.modules.identity.domain.user import CurrentUser
from drugtime.shared.clock import now
from drugtime.shared.config import get_settings

router = APIRouter(
    prefix="/me/email-change",
    tags=["identity"],
    dependencies=[Depends(HTTPBearer(auto_error=False, scheme_name="bearerAuth"))],
)


class StartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    new_email: str = Field(max_length=254, json_schema_extra={"format": "email"})


class VerifyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    challenge_id: UUID
    otp: str = Field(min_length=6, max_length=6, pattern=r"^[0-9]{6}$")


class ChallengeResponse(BaseModel):
    challenge_id: UUID
    expires_at: datetime


class ErrorDetail(BaseModel):
    detail: str


class ValidationErrorItem(BaseModel):
    loc: list[str | int]
    msg: str
    type: str


class EmailChangeValidationError(BaseModel):
    detail: list[ValidationErrorItem]


_NO_STORE = {"headers": {"Cache-Control": {"schema": {"type": "string", "const": "no-store"}}}}
_ERRORS = {
    **{code: {"model": ErrorDetail, **_NO_STORE} for code in (401, 403, 409, 429, 503)},
    422: {"model": ErrorDetail | EmailChangeValidationError, **_NO_STORE},
}


def get_email_change() -> EmailChange:
    return EmailChange(
        account_lock,
        SqlEmailChange(),
        SupabaseAuth(),
        send_email_change_otp,
        now,
        get_settings().email_change_otp_hmac_key.encode(),
    )


def _no_query(request: Request) -> None:
    if request.query_params:
        raise RequestValidationError(
            [{"loc": ["query"], "msg": "Unexpected query parameters", "type": "extra_forbidden"}]
        )


@router.post(
    "/otp",
    status_code=201,
    operation_id="startEmailChange",
    responses={201: _NO_STORE, **_ERRORS},
    dependencies=[Depends(_no_query)],
)
def start_email_change(
    body: StartRequest,
    user: CurrentUser = Depends(current_mobile_user),
    service: EmailChange = Depends(get_email_change),
) -> ChallengeResponse:
    challenge, expires = service.start(user.id, body.new_email)
    return ChallengeResponse(challenge_id=challenge, expires_at=expires.astimezone(UTC))


@router.post(
    "/verify-current",
    operation_id="verifyCurrentEmailChange",
    responses={200: _NO_STORE, **_ERRORS},
    dependencies=[Depends(_no_query)],
)
def verify_current_email(
    body: VerifyRequest,
    user: CurrentUser = Depends(current_mobile_user),
    service: EmailChange = Depends(get_email_change),
) -> ChallengeResponse:
    challenge, expires = service.verify_current(user.id, body.challenge_id, body.otp)
    return ChallengeResponse(challenge_id=challenge, expires_at=expires.astimezone(UTC))


@router.post(
    "/confirm",
    status_code=204,
    operation_id="confirmEmailChange",
    responses={204: _NO_STORE, **_ERRORS},
    dependencies=[Depends(_no_query)],
)
def confirm_email_change(
    body: VerifyRequest,
    user: CurrentUser = Depends(current_mobile_user),
    service: EmailChange = Depends(get_email_change),
) -> Response:
    service.confirm(user.id, body.challenge_id, body.otp)
    return Response(status_code=204)
