"""FastAPI dependencies shared by endpoints that need identity."""

from uuid import UUID

from fastapi import Depends, Header

from drugtime.modules.identity.adapters.outbound.sql_users import SqlUsers
from drugtime.modules.identity.application.sign_in import decode_app_session
from drugtime.modules.identity.domain.user import CurrentUser, SessionType
from drugtime.shared.db import SqlUnitOfWork, get_uow, read_unit_of_work, unit_of_work
from drugtime.shared.errors import Forbidden, Unauthorized

_SESSION_TYPES = {str(t) for t in SessionType}


def _decode(token: str) -> dict:
    """Chỉ nhận phiên do backend cấp (`aud=drugtime`); token Supabase bị từ chối."""
    payload = decode_app_session(token)
    if payload.get("typ") not in _SESSION_TYPES:
        raise Unauthorized("Invalid bearer token")
    return payload


def _authenticated_user_id(authorization: str | None) -> UUID:
    # Header tùy chọn để thiếu header trả 401 (contract), không phải 422 của FastAPI.
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise Unauthorized("Missing bearer token")
    try:
        return UUID(_decode(token)["sub"])
    except (KeyError, ValueError) as exc:
        raise Unauthorized("Invalid bearer token") from exc


def _read_current_user(user_id: UUID, uow: SqlUnitOfWork) -> CurrentUser:
    user = SqlUsers(uow).get(user_id)
    if user is None or user.erased:
        raise Unauthorized("Account does not exist or has been deleted")
    return CurrentUser(id=user.id, is_admin=user.is_admin)


def current_user(
    authorization: str | None = Header(None), uow: SqlUnitOfWork = Depends(get_uow)
) -> CurrentUser:
    return _read_current_user(_authenticated_user_id(authorization), uow)


def current_user_short_uow(authorization: str | None = Header(None)) -> CurrentUser:
    """Release the identity connection before a handler opens its own transaction."""
    user_id = _authenticated_user_id(authorization)
    with read_unit_of_work() as uow:
        return _read_current_user(user_id, uow)


def require_admin(user: CurrentUser = Depends(current_user)) -> CurrentUser:
    if not user.is_admin:
        raise Forbidden("admin_only")
    return user


def current_mobile_user(
    authorization: str | None = Header(None),
) -> CurrentUser:
    with unit_of_work() as uow:
        user = current_user(authorization, uow)
        _, _, token = (authorization or "").partition(" ")
        if user.is_admin or _decode(token).get("typ") != SessionType.MOBILE:
            raise Forbidden("khong_co_quyen")
        return user
