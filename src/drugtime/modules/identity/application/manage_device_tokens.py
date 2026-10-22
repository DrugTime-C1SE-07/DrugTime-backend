from uuid import UUID

from drugtime.modules.identity.application.ports import DeviceTokens
from drugtime.shared.errors import Forbidden
from drugtime.shared.uow import UnitOfWork


def register(
    uow: UnitOfWork,
    *,
    user_id: UUID,
    is_admin: bool,
    fcm_token: str,
    previous_fcm_token: str | None,
    tokens: DeviceTokens,
) -> None:
    if is_admin:
        raise Forbidden("khong_co_quyen")
    # Truyền token cũ cùng thao tác đăng ký để lỗi token mới không làm mất token cũ.
    tokens.register(uow, user_id, fcm_token, previous_fcm_token)


def unregister(
    uow: UnitOfWork, *, user_id: UUID, is_admin: bool, fcm_token: str, tokens: DeviceTokens
) -> None:
    if is_admin:
        raise Forbidden("khong_co_quyen")
    # Repository chỉ xóa token của caller; thiếu token hoặc khác chủ vẫn idempotent.
    tokens.unregister(uow, user_id, fcm_token)
