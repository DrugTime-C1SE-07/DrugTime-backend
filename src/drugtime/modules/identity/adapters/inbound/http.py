from datetime import date

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from drugtime.modules.identity.adapters.inbound.dependencies import current_user
from drugtime.modules.identity.adapters.outbound.sql_users import SqlUsers
from drugtime.modules.identity.adapters.outbound.supabase_auth import SupabaseAuth
from drugtime.modules.identity.application import sign_in
from drugtime.modules.identity.domain.user import CurrentUser
from drugtime.shared.clock import now
from drugtime.shared.db import SqlUnitOfWork, get_uow

router = APIRouter(prefix="/auth", tags=["identity"])


class RegisterRequest(BaseModel):
    email: str
    ho_ten: str
    so_dien_thoai: str
    ngay_sinh: date
    gioi_tinh: str


class OtpRequest(BaseModel):
    phone: str | None = None
    email: str | None = None


class OtpVerifyRequest(OtpRequest):
    token: str


class CompleteProfileRequest(BaseModel):
    ho_ten: str
    ngay_sinh: date
    gioi_tinh: str


class AdminLoginRequest(BaseModel):
    email: str
    password: str


class AdminSessionRefreshRequest(BaseModel):
    session_token: str


@router.post("/register")
def register(body: RegisterRequest, uow: SqlUnitOfWork = Depends(get_uow)) -> dict:
    return sign_in.register_user(
        SupabaseAuth(),
        SqlUsers(uow),
        email=body.email,
        ho_ten=body.ho_ten,
        so_dien_thoai=body.so_dien_thoai,
        ngay_sinh=body.ngay_sinh,
        gioi_tinh=body.gioi_tinh,
        now=now(),
    )


@router.post("/mobile/otp", status_code=204)
def request_mobile_otp(body: OtpRequest) -> None:
    sign_in.request_mobile_otp(SupabaseAuth(), phone=body.phone, email=body.email)


@router.post("/mobile/verify")
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


@router.post("/profile", status_code=204)
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


@router.post("/admin/login")
def login_admin(body: AdminLoginRequest, uow: SqlUnitOfWork = Depends(get_uow)) -> dict:
    return sign_in.login_admin(
        SupabaseAuth(),
        SqlUsers(uow),
        email=body.email,
        password=body.password,
        now=now(),
    )


@router.post("/admin/session/refresh")
def refresh_admin_session(
    body: AdminSessionRefreshRequest, uow: SqlUnitOfWork = Depends(get_uow)
) -> dict:
    return sign_in.refresh_admin_session(SqlUsers(uow), session_token=body.session_token, now=now())
