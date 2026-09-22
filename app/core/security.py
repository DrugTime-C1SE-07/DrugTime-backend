"""Security and authentication utilities for DrugTime API."""
from typing import Optional, Literal
from pydantic import BaseModel
from fastapi import Header, HTTPException, status
from app.mock_db import db

class CurrentUser(BaseModel):
    user_id: str
    ho_ten: str
    vai_tro_he_thong: Literal["user", "admin"] = "user"

def get_current_user(authorization: Optional[str] = Header(None)) -> CurrentUser:
    """
    Extracts user identity from Supabase Bearer JWT.
    For local development and scaffolding, supports both JWT tokens and shorthand Bearer tokens:
    - 'Bearer usr-patient-1'
    - 'Bearer usr-family-1'
    - 'Bearer usr-family-readonly'
    - 'Bearer usr-admin-1'
    Defaults to 'usr-patient-1' if no header provided in dev mode.
    """
    if not authorization:
        # Default fallback for testing/swagger without auth header
        user = db.users.get("usr-patient-1")
        return CurrentUser(user_id=user["id"], ho_ten=user["ho_ten"], vai_tro_he_thong=user["vai_tro_he_thong"])

    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "INVALID_TOKEN", "message": "Header Authorization không đúng định dạng 'Bearer <token>'"}
        )

    token = parts[1]
    
    # Check if token matches a mock user id
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
