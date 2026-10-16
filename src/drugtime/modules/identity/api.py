"""Giao diện công khai của identity. Module khác chỉ import file này."""

from datetime import date, datetime
from uuid import UUID

from drugtime.modules.identity.adapters.inbound.dependencies import current_user, require_admin
from drugtime.modules.identity.adapters.inbound.http import router
from drugtime.modules.identity.adapters.outbound.sql_users import SqlUsers
from drugtime.modules.identity.adapters.outbound.supabase_auth import SupabaseAuth
from drugtime.modules.identity.application import erase_user as _erase
from drugtime.modules.identity.application import profile as _profile
from drugtime.modules.identity.domain.profile import ProfileRecord
from drugtime.modules.identity.domain.user import CurrentUser
from drugtime.shared.uow import UnitOfWork

__all__ = [
    "display_names",
    "ProfileRecord",
    "get_profile",
    "update_profile",
    "CurrentUser",
    "account_remover",
    "android_tokens",
    "current_user",
    "eraser",
    "require_admin",
    "router",
    "user_emails",
    "user_exists",
]


def user_exists(uow: UnitOfWork, user_id: UUID) -> bool:
    """Có dòng users với id này (kể cả tài khoản đã xoá dữ liệu)."""
    return SqlUsers(uow).get(user_id) is not None


def get_profile(uow: UnitOfWork, user_id: UUID) -> ProfileRecord:
    return _profile.get_profile(SqlUsers(uow), user_id)


def update_profile(
    uow: UnitOfWork,
    user_id: UUID,
    *,
    full_name: str,
    date_of_birth: date,
    gender: str,
    at: datetime,
) -> None:
    _profile.update_profile(
        SqlUsers(uow),
        user_id,
        full_name=full_name,
        date_of_birth=date_of_birth,
        gender=gender,
        at=at,
    )


def user_emails(uow: UnitOfWork, user_ids: list[UUID]) -> dict[UUID, str | None]:
    """Email hiện tại của các user (None nếu đã xoá dữ liệu); id không tồn tại thì bị bỏ qua."""
    return SqlUsers(uow).emails(list(user_ids))


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


def display_names(uow: UnitOfWork, user_ids: list[UUID]) -> dict[UUID, str | None]:
    """Minimal name projection; missing/erased accounts are omitted."""
    return SqlUsers(uow).display_names(user_ids)
