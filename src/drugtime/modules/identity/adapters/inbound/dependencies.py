"""FastAPI dependency dùng chung: mọi endpoint xác thực qua identity (note trên sơ đồ L3)."""

from functools import lru_cache
from uuid import UUID

import jwt
from fastapi import Depends, Header

from drugtime.modules.identity.adapters.outbound.sql_users import SqlUsers
from drugtime.modules.identity.domain.user import CurrentUser
from drugtime.shared.config import get_settings
from drugtime.shared.db import SqlUnitOfWork, get_uow
from drugtime.shared.errors import Forbidden, Unauthorized


@lru_cache
def _jwks_client() -> jwt.PyJWKClient:
    return jwt.PyJWKClient(get_settings().supabase_jwks_url)


def _decode(token: str) -> dict:
    s = get_settings()
    try:
        if s.supabase_jwks_url:
            key = _jwks_client().get_signing_key_from_jwt(token).key
            return jwt.decode(token, key, algorithms=["RS256", "ES256"], audience="authenticated")
        return jwt.decode(
            token, s.supabase_jwt_secret, algorithms=["HS256"], audience="authenticated"
        )
    except jwt.PyJWTError as exc:
        raise Unauthorized("Token không hợp lệ") from exc


def current_user(
    authorization: str = Header(...), uow: SqlUnitOfWork = Depends(get_uow)
) -> CurrentUser:
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise Unauthorized("Thiếu bearer token")
    user = SqlUsers(uow).get(UUID(_decode(token)["sub"]))
    if user is None or user.erased:
        raise Unauthorized("Tài khoản không tồn tại hoặc đã bị xóa")
    return CurrentUser(id=user.id, is_admin=user.is_admin)


def require_admin(user: CurrentUser = Depends(current_user)) -> CurrentUser:
    if not user.is_admin:
        raise Forbidden("Chỉ dành cho Admin")
    return user
