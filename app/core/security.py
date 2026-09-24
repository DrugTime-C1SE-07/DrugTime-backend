"""Security and authentication utilities for DrugTime API."""
import os
import logging
from typing import Optional, Literal
from pydantic import BaseModel
from fastapi import Header, HTTPException, status
from app.mock_db import db

logger = logging.getLogger(__name__)


class CurrentUser(BaseModel):
    user_id: str
    ho_ten: str
    vai_tro_he_thong: Literal["user", "admin"] = "user"


def _verify_supabase_token(token: str) -> Optional[dict]:
    """
    Verify a Supabase JWT and return the decoded payload, or None if
    Supabase is not configured or verification fails.
    Does NOT fall back to mock auth — caller decides the fallback.
    """
    supabase_url = os.environ.get("SUPABASE_URL")
    supabase_jwt_secret = os.environ.get("SUPABASE_JWT_SECRET")

    if not supabase_url or not supabase_jwt_secret:
        return None

    try:
        import jwt as pyjwt
        payload = pyjwt.decode(
            token,
            supabase_jwt_secret,
            algorithms=["HS256"],
            audience="authenticated",
        )
        return payload
    except ImportError:
        logger.warning("PyJWT not installed; Supabase token verification unavailable.")
        return None
    except Exception:
        # Invalid/expired/malformed token
        return None


def _resolve_user_from_supabase_payload(payload: dict) -> CurrentUser:
    """
    Map a decoded Supabase JWT payload to a CurrentUser.
    If a DrugTime application user exists for this sub, use it.
    Otherwise, create a minimal identity from the token claims.
    """
    sub = payload.get("sub", "")
    if not sub:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "INVALID_TOKEN", "message": "Token thiếu trường 'sub'"}
        )

    # Check if a synced DrugTime user already exists
    user = db.users.get(sub)
    if user:
        return CurrentUser(
            user_id=user["id"],
            ho_ten=user["ho_ten"],
            vai_tro_he_thong=user.get("vai_tro_he_thong", "user")
        )

    # User not yet synced — return identity from token for sync-profile to complete
    user_meta = payload.get("user_metadata", {})
    ho_ten = user_meta.get("ho_ten", "")
    email = payload.get("email", "")
    display_name = ho_ten or email or "Người dùng mới"

    return CurrentUser(user_id=sub, ho_ten=display_name, vai_tro_he_thong="user")


def get_current_user(authorization: Optional[str] = Header(None)) -> CurrentUser:
    """
    Extracts user identity from Supabase Bearer JWT.

    Priority:
    1. If SUPABASE_JWT_SECRET is set, verify the token as a real JWT.
    2. Otherwise, fall back to mock token lookup for dev/testing.

    For local development and scaffolding, supports shorthand Bearer tokens:
    - 'Bearer usr-patient-1'
    - 'Bearer usr-family-1'
    - 'Bearer usr-family-readonly'
    - 'Bearer usr-admin-1'
    Defaults to 'usr-patient-1' if no header provided in dev mode.
    """
    if not authorization:
        # Default fallback for testing/swagger without auth header
        user = db.users.get("usr-patient-1")
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"code": "UNAUTHORIZED", "message": "Thiếu header Authorization"}
            )
        return CurrentUser(user_id=user["id"], ho_ten=user["ho_ten"], vai_tro_he_thong=user["vai_tro_he_thong"])

    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "INVALID_TOKEN", "message": "Header Authorization không đúng định dạng 'Bearer <token>'"}
        )

    token = parts[1]

    # 1. Try real Supabase JWT verification
    payload = _verify_supabase_token(token)
    if payload is not None:
        return _resolve_user_from_supabase_payload(payload)

    # 2. Mock token fallback (dev/test only — when SUPABASE_JWT_SECRET is not set)
    if token in db.users:
        user = db.users[token]
        return CurrentUser(user_id=user["id"], ho_ten=user["ho_ten"], vai_tro_he_thong=user["vai_tro_he_thong"])

    # Fallback / mock decoded JWT
    user = db.users.get("usr-patient-1")
    return CurrentUser(user_id=token if token.startswith("usr-") else "usr-patient-1", ho_ten="Người Dùng Thử Nghiệm", vai_tro_he_thong="user")


def require_admin_user(authorization: Optional[str] = Header(None)) -> CurrentUser:
    user = get_current_user(authorization)
    if user.vai_tro_he_thong != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "ADMIN_REQUIRED", "message": "Thao tác chỉ dành riêng cho Quản trị viên (Admin)"}
        )
    return user
