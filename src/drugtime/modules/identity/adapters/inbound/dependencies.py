"""FastAPI dependencies shared by endpoints that need identity."""

from uuid import UUID

from fastapi import Depends, Header

from drugtime.modules.identity.adapters.outbound.sql_users import SqlUsers
from drugtime.modules.identity.application.sign_in import decode_app_session
from drugtime.modules.identity.domain.user import CurrentUser, SessionType
from drugtime.shared.db import SqlUnitOfWork, get_uow
from drugtime.shared.errors import Forbidden, Unauthorized

_SESSION_TYPES = {str(t) for t in SessionType}


def _decode(token: str) -> dict:
    """Chỉ nhận phiên do backend cấp (`aud=drugtime`); token Supabase bị từ chối."""
    payload = decode_app_session(token)
    if payload.get("typ") not in _SESSION_TYPES:
        raise Unauthorized("Invalid bearer token")
    return payload


def current_user(
    authorization: str | None = Header(None), uow: SqlUnitOfWork = Depends(get_uow)
) -> CurrentUser:
    # Header tùy chọn để thiếu header trả 401 (contract), không phải 422 của FastAPI.
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise Unauthorized("Missing bearer token")
    try:
        user_id = UUID(_decode(token)["sub"])
    except (KeyError, ValueError) as exc:
        raise Unauthorized("Invalid bearer token") from exc
    user = SqlUsers(uow).get(user_id)
    if user is None or user.erased:
        raise Unauthorized("Account does not exist or has been deleted")
    return CurrentUser(id=user.id, is_admin=user.is_admin)


def require_admin(user: CurrentUser = Depends(current_user)) -> CurrentUser:
    if not user.is_admin:
        raise Forbidden("admin_only")
    return user
