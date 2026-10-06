import re
from datetime import date, datetime, timedelta
from uuid import UUID

import jwt

from drugtime.modules.identity.application.ports import AuthProvider, UserRepository
from drugtime.modules.identity.domain.user import AppSession, SessionType
from drugtime.shared.config import get_settings
from drugtime.shared.errors import DomainError, Forbidden, Unauthorized

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_GENDERS = {"nam", "nu", "khac", "male", "female", "other"}


def request_mobile_otp(auth: AuthProvider, *, phone: str | None, email: str | None) -> None:
    phone, email = _validate_one_login_identifier(phone=phone, email=email)
    auth.request_otp(phone=phone, email=email, create_user=True)


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
    token = (token or "").strip()
    if not token:
        # Mã rỗng sau khi bỏ khoảng trắng: coi như sai mã, không gọi Supabase.
        raise Unauthorized("Invalid credentials")
    supabase_session = auth.verify_otp(phone=phone, email=email, token=token)
    user_id = _user_id_from_session(supabase_session)

    user = users.get(user_id)
    if user is None:
        users.create_minimal(user_id, phone=phone, email=email)
        user = users.get(user_id)

    if user.erased:
        raise Unauthorized("Account cannot be authenticated")
    if user.is_admin:
        raise Forbidden("admin_must_use_web")

    app_session = issue_app_session(user_id, SessionType.MOBILE, now)
    result = _auth_response(user_id, app_session)
    result["profile_complete"] = user.profile_complete
    return result


def complete_profile(
    users: UserRepository,
    *,
    user_id: UUID,
    ho_ten: str,
    ngay_sinh: date,
    gioi_tinh: str,
    now: datetime,
) -> None:
    full_name, gender = _validate_profile(
        ho_ten=ho_ten, ngay_sinh=ngay_sinh, gioi_tinh=gioi_tinh, now=now
    )
    users.update_profile(user_id, full_name=full_name, date_of_birth=ngay_sinh, gender=gender)


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
        raise Forbidden("admin_required")
    app_session = issue_app_session(user_id, SessionType.ADMIN_WEB, now)
    return _auth_response(user_id, app_session)


def refresh_admin_session(users: UserRepository, *, session_token: str, now: datetime) -> dict:
    payload = decode_app_session(session_token)
    if payload.get("typ") != str(SessionType.ADMIN_WEB):
        raise Unauthorized("Invalid admin session")
    user_id = UUID(payload["sub"])
    user = users.get(user_id)
    if user is None or user.erased:
        raise Unauthorized("Account cannot be authenticated")
    if not user.is_admin:
        raise Forbidden("admin_required")
    app_session = issue_app_session(user_id, SessionType.ADMIN_WEB, now)
    return {"user_id": str(user_id), "session": _session_to_dict(app_session)}


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


def _auth_response(user_id: UUID, app_session: AppSession) -> dict:
    # Không trả token Supabase: client chỉ dùng phiên do backend cấp.
    return {"user_id": str(user_id), "session": _session_to_dict(app_session)}


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
    email = _validate_required_text(value, "invalid_email").lower()
    if not _EMAIL_RE.match(email):
        raise DomainError("invalid_email")
    return email


def _validate_password(value: str) -> None:
    password = _validate_required_text(value, "password_too_short")
    if len(password) < 8:
        raise DomainError("password_too_short")


def _validate_required_text(value: str | None, error_code: str) -> str:
    cleaned = (value or "").strip()
    if not cleaned:
        raise DomainError(error_code)
    return cleaned


def _validate_one_login_identifier(
    *, phone: str | None, email: str | None
) -> tuple[str | None, str | None]:
    has_phone = phone is not None and phone.strip() != ""
    has_email = email is not None and email.strip() != ""
    if has_phone == has_email:
        raise DomainError("login_identifier_required")
    if has_phone:
        return _normalize_phone(phone), None
    return None, _validate_email(email or "")


def _normalize_phone(value: str | None) -> str:
    phone = _validate_required_text(value, "invalid_phone")
    phone = phone.replace(" ", "").replace("-", "")
    if phone.startswith("0") and phone[1:].isdigit():
        phone = "+84" + phone[1:]
    if not phone.startswith("+") or not phone[1:].isdigit():
        raise DomainError("invalid_phone")
    if len(phone) < 9 or len(phone) > 16:
        raise DomainError("invalid_phone")
    return phone


def _validate_gender(value: str) -> str:
    gender = _validate_required_text(value, "invalid_gender").lower()
    if gender not in _GENDERS:
        raise DomainError("invalid_gender")
    return gender


def _validate_profile(
    *,
    ho_ten: str,
    ngay_sinh: date,
    gioi_tinh: str,
    now: datetime,
) -> tuple[str, str]:
    full_name = _validate_required_text(ho_ten, "invalid_full_name")
    gender = _validate_gender(gioi_tinh)
    _validate_birth_date(ngay_sinh, now)
    return full_name, gender


def _validate_birth_date(value: date, now: datetime) -> None:
    if value > now.date():
        raise DomainError("invalid_date_of_birth")
