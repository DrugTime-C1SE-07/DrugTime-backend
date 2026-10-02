from datetime import date, datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from drugtime.modules.identity.adapters.inbound.dependencies import current_user
from drugtime.modules.identity.adapters.outbound.sql_users import SqlUsers
from drugtime.modules.identity.adapters.outbound.supabase_auth import SupabaseAuth
from drugtime.modules.identity.application import sign_in
from drugtime.modules.identity.domain.user import CurrentUser
from drugtime.shared.clock import now
from drugtime.shared.db import SqlUnitOfWork, get_uow

router = APIRouter(prefix="/auth", tags=["identity"])


class ErrorOut(BaseModel):
    detail: str


def _errors(*codes: int) -> dict:
    """Khai báo mã lỗi để OpenAPI sinh ra khớp contract (body do handler chung trong main.py)."""
    return {code: {"model": ErrorOut} for code in codes}


class OtpRequest(BaseModel):
    phone: str | None = None
    email: str | None = None


class OtpVerifyRequest(OtpRequest):
    token: str = Field(min_length=1)


class CompleteProfileRequest(BaseModel):
    ho_ten: str
    ngay_sinh: date
    gioi_tinh: str


class AdminLoginRequest(BaseModel):
    email: str
    password: str


class AdminSessionRefreshRequest(BaseModel):
    session_token: str


class AppSessionOut(BaseModel):
    access_token: str
    token_type: Literal["bearer"]
    session_type: Literal["mobile", "admin_web"]
    expires_at: datetime
    expires_in: int


class MobileAuthResultOut(BaseModel):
    user_id: UUID
    session: AppSessionOut
    profile_complete: bool


class AdminAuthResultOut(BaseModel):
    user_id: UUID
    session: AppSessionOut


@router.post("/mobile/otp", status_code=204, responses=_errors(422, 429, 503))
def request_mobile_otp(body: OtpRequest) -> None:
    sign_in.request_mobile_otp(SupabaseAuth(), phone=body.phone, email=body.email)


@router.post(
    "/mobile/verify",
    response_model=MobileAuthResultOut,
    responses=_errors(401, 403, 429, 503),
)
def verify_mobile_otp(
    body: OtpVerifyRequest, uow: SqlUnitOfWork = Depends(get_uow)
) -> dict:
    return sign_in.verify_mobile_otp(
        SupabaseAuth(),
        SqlUsers(uow),
        phone=body.phone,
        email=body.email,
        token=body.token,
        now=now(),
    )


@router.post("/profile", status_code=204, responses=_errors(401))
def complete_profile(
    body: CompleteProfileRequest,
    user: CurrentUser = Depends(current_user),
    uow: SqlUnitOfWork = Depends(get_uow),
) -> None:
    sign_in.complete_profile(
        SqlUsers(uow),
        user_id=user.id,
        ho_ten=body.ho_ten,
        ngay_sinh=body.ngay_sinh,
        gioi_tinh=body.gioi_tinh,
        now=now(),
    )


@router.post(
    "/admin/login",
    response_model=AdminAuthResultOut,
    responses=_errors(401, 403, 429, 503),
)
def login_admin(body: AdminLoginRequest, uow: SqlUnitOfWork = Depends(get_uow)) -> dict:
    return sign_in.login_admin(
        SupabaseAuth(),
        SqlUsers(uow),
        email=body.email,
        password=body.password,
        now=now(),
    )


@router.post(
    "/admin/session/refresh",
    response_model=AdminAuthResultOut,
    responses=_errors(401, 403),
)
def refresh_admin_session(
    body: AdminSessionRefreshRequest, uow: SqlUnitOfWork = Depends(get_uow)
) -> dict:
    return sign_in.refresh_admin_session(SqlUsers(uow), session_token=body.session_token, now=now())
