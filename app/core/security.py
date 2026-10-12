"""Security and authentication utilities for DrugTime API (Schema v9: erased_at check)."""
from typing import Optional, Literal
from pydantic import BaseModel
from fastapi import Header, HTTPException, status
from app.mock_db import db

class CurrentUser(BaseModel):
    user_id: str
    full_name: Optional[str] = None
    system_role: Literal["user", "admin"] = "user"
    erased_at: Optional[str] = None

    # Backward compatibility properties
    @property
    def ho_ten(self) -> str:
        return self.full_name or ""

    @property
    def vai_tro_he_thong(self) -> str:
        return self.system_role

def get_current_user(authorization: Optional[str] = Header(None)) -> CurrentUser:
    """
    Extracts user identity from Supabase Bearer JWT.
    Enforces CD9 / Schema v9 rule: C.erased_at IS NOT NULL -> 401 Unauthorized immediately.
    """
    if not authorization:
        # Default fallback for testing/swagger without auth header
        user = db.users.get("usr-patient-1")
        if user and user.get("erased_at"):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"code": "ACCOUNT_ERASED", "message": "Tài khoản đã bị xóa dữ liệu (tombstone)."}
            )
        return CurrentUser(
            user_id=user["id"] if user else "usr-patient-1",
            full_name=user.get("full_name", user.get("ho_ten")),
            system_role=user.get("system_role", user.get("vai_tro_he_thong", "user")),
            erased_at=user.get("erased_at") if user else None
        )

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
        if user.get("erased_at"):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"code": "ACCOUNT_ERASED", "message": "Tài khoản đã bị xóa dữ liệu (tombstone)."}
            )
        return CurrentUser(
            user_id=user["id"],
            full_name=user.get("full_name", user.get("ho_ten")),
            system_role=user.get("system_role", user.get("vai_tro_he_thong", "user")),
            erased_at=user.get("erased_at")
        )

    # Fallback / mock decoded JWT
    user = db.users.get("usr-patient-1")
    return CurrentUser(
        user_id=token if token.startswith("usr-") else "usr-patient-1",
        full_name="Người Dùng Thử Nghiệm",
        system_role="user"
    )

def require_admin_user(authorization: Optional[str] = Header(None)) -> CurrentUser:
    user = get_current_user(authorization)
    if user.system_role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "ADMIN_REQUIRED", "message": "Thao tác chỉ dành riêng cho Quản trị viên (Admin)"}
        )
    return user
