import re
from datetime import UTC, date, datetime, timedelta
from uuid import UUID

import jwt

from drugtime.modules.identity.application.ports import AuthProvider, UserRepository
from drugtime.modules.identity.domain.user import (
    AccountType,
    AppSession,
    RegistrationProfile,
    SessionType,
)
from drugtime.shared.config import get_settings
from drugtime.shared.errors import DomainError, Forbidden, Unauthorized

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_GENDERS = {"nam", "nu", "khac", "male", "female", "other"}
_ACCOUNT_TYPES = {
    "patient": AccountType.PATIENT,
    "benh_nhan": AccountType.PATIENT,
    "family_member": AccountType.FAMILY_MEMBER,
    "nguoi_than": AccountType.FAMILY_MEMBER,
}


def register_user(
    auth: AuthProvider,
    users: UserRepository,
    *,
    email: str,
    ho_ten: str,
    so_dien_thoai: str,
    ngay_sinh: date,
    gioi_tinh: str,
    loai_tai_khoan: str,
    now: datetime,
) -> dict:
    email = _validate_email(email)
    phone = _normalize_phone(so_dien_thoai)
    full_name, gender, account_type = _validate_registration_profile(
        ho_ten=ho_ten,
        ngay_sinh=ngay_sinh,
        gioi_tinh=gioi_tinh,
        loai_tai_khoan=loai_tai_khoan,
        now=now,
    )

    session = auth.create_user_without_password(email=email, phone=phone)
    user_id = _user_id_from_session(session)
    profile = RegistrationProfile(
        id=user_id,
        email=email,
        phone_number=phone,
        full_name=full_name,
        date_of_birth=ngay_sinh,
        gender=gender,
        account_type=account_type,
    )
    try:
        users.create_registered_user(profile)
    except Exception:
        # If public.users fails, remove the Supabase Auth account to avoid a half-created user.
        auth.delete_account(user_id)
        raise
    return {
        "user_id": str(user_id),
        "account_type": str(account_type),
        "supabase": session,
    }


def request_mobile_otp(auth: AuthProvider, *, phone: str | None, email: str | None) -> None:
    phone, email = _validate_one_login_identifier(phone=phone, email=email)
    auth.request_otp(phone=phone, email=email, create_user=False)


def verify_mobile_otp(
    auth: AuthProvider,
    users: UserRepository,
    *,
    phone: str | None,
    email: str | None,
    token: str,
    now: datetime,
) -> dict:
    phone, email = _validate_one_login_identifier(phone=phone, email=email)
    token = _validate_required_text(token, "token")
    supabase_session = auth.verify_otp(phone=phone, email=email, token=token)
    user_id = _user_id_from_session(supabase_session)
    user = users.get(user_id)
    if user is None or user.erased:
        raise Unauthorized("Account cannot be authenticated")
    if user.is_admin:
        raise Forbidden("Admin accounts must use admin web login")
    app_session = issue_app_session(user_id, SessionType.MOBILE, now)
    return _auth_response(user_id, supabase_session, app_session)


def login_admin(
    auth: AuthProvider,
    users: UserRepository,
    *,
    email: str,
    password: str,
    now: datetime,
) -> dict:
    email = _validate_email(email)
    _validate_password(password)
    supabase_session = auth.login_with_password(email=email, password=password)
    user_id = _user_id_from_session(supabase_session)
    user = users.get(user_id)
    if user is None or user.erased:
        raise Unauthorized("Account cannot be authenticated")
    if not user.is_admin:
        raise Forbidden("Admin access required")
    app_session = issue_app_session(user_id, SessionType.ADMIN_WEB, now)
    return _auth_response(user_id, supabase_session, app_session)


def refresh_admin_session(users: UserRepository, *, session_token: str, now: datetime) -> dict:
    payload = decode_app_session(session_token)
    if payload.get("typ") != str(SessionType.ADMIN_WEB):
        raise Unauthorized("Invalid admin session")
    user_id = UUID(payload["sub"])
    user = users.get(user_id)
    if user is None or user.erased:
        raise Unauthorized("Account cannot be authenticated")
    if not user.is_admin:
        raise Forbidden("Admin access required")
    app_session = issue_app_session(user_id, SessionType.ADMIN_WEB, now)
    return {"user_id": str(user_id), "session": _session_to_dict(app_session)}


def request_otp(auth: AuthProvider, *, phone: str | None, email: str | None) -> None:
    request_mobile_otp(auth, phone=phone, email=email)


def verify_otp(
    auth: AuthProvider,
    users: UserRepository,
    *,
    phone: str | None,
    email: str | None,
    token: str,
) -> dict:
    return verify_mobile_otp(
        auth,
        users,
        phone=phone,
        email=email,
        token=token,
        now=datetime.now(UTC),
    )


def issue_app_session(user_id: UUID, session_type: SessionType, now: datetime) -> AppSession:
    settings = get_settings()
    if session_type is SessionType.MOBILE:
        lifetime = timedelta(days=settings.mobile_session_days)
    else:
        lifetime = timedelta(minutes=settings.admin_session_idle_minutes)
    expires_at = now + lifetime
    payload = {
        "sub": str(user_id),
        "aud": "drugtime",
        "typ": str(session_type),
        "iat": int(now.timestamp()),
        "exp": int(expires_at.timestamp()),
    }
    token = jwt.encode(payload, _session_secret(), algorithm="HS256")
    return AppSession(
        token=token,
        session_type=session_type,
        expires_at=expires_at,
        expires_in_seconds=int(lifetime.total_seconds()),
    )


def decode_app_session(token: str) -> dict:
    try:
        return jwt.decode(token, _session_secret(), algorithms=["HS256"], audience="drugtime")
    except jwt.PyJWTError as exc:
        raise Unauthorized("Invalid or expired session") from exc


def _auth_response(user_id: UUID, supabase_session: dict, app_session: AppSession) -> dict:
    return {
        "user_id": str(user_id),
        "supabase": supabase_session,
        "session": _session_to_dict(app_session),
    }


def _session_to_dict(session: AppSession) -> dict:
    return {
        "access_token": session.token,
        "token_type": "bearer",
        "session_type": str(session.session_type),
        "expires_at": session.expires_at.isoformat(),
        "expires_in": session.expires_in_seconds,
    }


def _session_secret() -> str:
    settings = get_settings()
    secret = settings.session_jwt_secret or settings.supabase_jwt_secret
    if not secret:
        raise DomainError("SESSION_JWT_SECRET is not configured")
    return secret


def _user_id_from_session(session: dict) -> UUID:
    try:
        user_id = session.get("id") or session["user"]["id"]
        return UUID(user_id)
    except (KeyError, TypeError, ValueError) as exc:
        raise Unauthorized("Authentication response is invalid") from exc


def _validate_email(value: str) -> str:
    email = _validate_required_text(value, "email").lower()
    if not _EMAIL_RE.match(email):
        raise DomainError("Invalid email")
    return email


def _validate_password(value: str) -> None:
    password = _validate_required_text(value, "password")
    if len(password) < 8:
        raise DomainError("Password must be at least 8 characters")


def _validate_required_text(value: str | None, field_name: str) -> str:
    if value is None:
        raise DomainError(f"{field_name} is required")
    cleaned = value.strip()
    if not cleaned:
        raise DomainError(f"{field_name} is required")
    return cleaned


def _validate_one_login_identifier(
    *, phone: str | None, email: str | None
) -> tuple[str | None, str | None]:
    has_phone = phone is not None and phone.strip() != ""
    has_email = email is not None and email.strip() != ""
    if has_phone == has_email:
        raise DomainError("Use exactly one of phone or email")
    if has_phone:
        return _normalize_phone(phone), None
    return None, _validate_email(email or "")


def _normalize_phone(value: str | None) -> str:
    phone = _validate_required_text(value, "so_dien_thoai")
    phone = phone.replace(" ", "").replace("-", "")
    if phone.startswith("0") and phone[1:].isdigit():
        phone = "+84" + phone[1:]
    if not phone.startswith("+") or not phone[1:].isdigit():
        raise DomainError("Phone number must be E.164")
    if len(phone) < 9 or len(phone) > 16:
        raise DomainError("Phone number must be E.164")
    return phone


def _validate_gender(value: str) -> str:
    gender = _validate_required_text(value, "gioi_tinh").lower()
    if gender not in _GENDERS:
        raise DomainError("Invalid gioi_tinh")
    return gender


def _validate_account_type(value: str) -> AccountType:
    account_type = _validate_required_text(value, "loai_tai_khoan").lower()
    if account_type not in _ACCOUNT_TYPES:
        raise DomainError("Invalid loai_tai_khoan")
    return _ACCOUNT_TYPES[account_type]


def _validate_registration_profile(
    *,
    ho_ten: str,
    ngay_sinh: date,
    gioi_tinh: str,
    loai_tai_khoan: str,
    now: datetime,
) -> tuple[str, str, AccountType]:
    full_name = _validate_required_text(ho_ten, "ho_ten")
    gender = _validate_gender(gioi_tinh)
    account_type = _validate_account_type(loai_tai_khoan)
    _validate_birth_date(ngay_sinh, now)
    return full_name, gender, account_type


def _validate_birth_date(value: date, now: datetime) -> None:
    if value > now.date():
        raise DomainError("ngay_sinh cannot be in the future")
