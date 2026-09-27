"""FastAPI dependencies shared by endpoints that need identity."""

from functools import lru_cache
from uuid import UUID

import jwt
from fastapi import Depends, Header

from drugtime.modules.identity.adapters.outbound.sql_users import SqlUsers
from drugtime.modules.identity.application.sign_in import decode_app_session
from drugtime.modules.identity.domain.user import CurrentUser
from drugtime.shared.config import get_settings
from drugtime.shared.db import SqlUnitOfWork, get_uow
from drugtime.shared.errors import Forbidden, Unauthorized


@lru_cache
def _jwks_client() -> jwt.PyJWKClient:
    return jwt.PyJWKClient(get_settings().supabase_jwks_url)


def _decode_supabase_token(token: str) -> dict:
    settings = get_settings()
    if settings.supabase_jwks_url:
        key = _jwks_client().get_signing_key_from_jwt(token).key
        return jwt.decode(token, key, algorithms=["RS256", "ES256"], audience="authenticated")
    return jwt.decode(
        token,
        settings.supabase_jwt_secret,
        algorithms=["HS256"],
        audience="authenticated",
    )


def _decode(token: str) -> dict:
    try:
        return _decode_supabase_token(token)
    except jwt.PyJWTError as exc:
        try:
            return decode_app_session(token)
        except Unauthorized:
            raise Unauthorized("Invalid bearer token") from exc


def current_user(
    authorization: str = Header(...), uow: SqlUnitOfWork = Depends(get_uow)
) -> CurrentUser:
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise Unauthorized("Missing bearer token")
    user = SqlUsers(uow).get(UUID(_decode(token)["sub"]))
    if user is None or user.erased:
        raise Unauthorized("Account does not exist or has been deleted")
    return CurrentUser(id=user.id, is_admin=user.is_admin)


def require_admin(user: CurrentUser = Depends(current_user)) -> CurrentUser:
    if not user.is_admin:
        raise Forbidden("Admin only")
    return user
