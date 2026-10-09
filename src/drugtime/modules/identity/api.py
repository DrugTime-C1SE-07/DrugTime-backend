"""Giao diện công khai của identity. Module khác chỉ import file này."""

from uuid import UUID

from drugtime.modules.identity.adapters.inbound.dependencies import current_user, require_admin
from drugtime.modules.identity.adapters.inbound.http import router
from drugtime.modules.identity.adapters.outbound.sql_users import SqlUsers
from drugtime.modules.identity.adapters.outbound.supabase_auth import SupabaseAuth
from drugtime.modules.identity.application import erase_user as _erase
from drugtime.modules.identity.domain.user import CurrentUser
from drugtime.shared.uow import UnitOfWork

__all__ = [
    "CurrentUser",
    "account_remover",
    "android_tokens",
    "current_user",
    "eraser",
    "require_admin",
    "router",
    "user_exists",
]


def user_exists(uow: UnitOfWork, user_id: UUID) -> bool:
    """Có dòng users với id này (kể cả tài khoản đã xoá dữ liệu)."""
    return SqlUsers(uow).get(user_id) is not None


def android_tokens(uow: UnitOfWork, user_ids: list[UUID]) -> list[tuple[UUID, str]]:
    """Token FCM Android của các user (iOS bị bỏ qua: không có APNs trong Phase 1)."""
    return SqlUsers(uow).device_tokens(user_ids, "android")


class _Eraser:
    name = "identity"

    def erase_user(self, uow: UnitOfWork, user_id: UUID) -> None:
        _erase.erase_user(SqlUsers(uow), user_id)


class _AccountRemover:
    def delete_account(self, user_id: UUID) -> None:
        _erase.delete_account(SupabaseAuth(), user_id)


eraser = _Eraser()
account_remover = _AccountRemover()
