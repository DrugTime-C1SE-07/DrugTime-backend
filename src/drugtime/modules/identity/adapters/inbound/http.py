from fastapi import APIRouter, Depends
from pydantic import BaseModel

from drugtime.modules.identity.adapters.outbound.sql_users import SqlUsers
from drugtime.modules.identity.adapters.outbound.supabase_auth import SupabaseAuth
from drugtime.modules.identity.application import sign_in
from drugtime.shared.db import SqlUnitOfWork, get_uow

router = APIRouter(prefix="/auth", tags=["identity"])


class OtpRequest(BaseModel):
    phone: str | None = None  # E.164, vd +84901234567
    email: str | None = None


class OtpVerify(OtpRequest):
    token: str


@router.post("/otp", status_code=204)
def request_otp(body: OtpRequest) -> None:
    sign_in.request_otp(SupabaseAuth(), phone=body.phone, email=body.email)


@router.post("/verify")
def verify_otp(body: OtpVerify, uow: SqlUnitOfWork = Depends(get_uow)) -> dict:
    return sign_in.verify_otp(
        SupabaseAuth(), SqlUsers(uow), phone=body.phone, email=body.email, token=body.token
    )
