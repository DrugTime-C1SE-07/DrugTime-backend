"""Giao diện công khai của identity. Module khác chỉ import file này."""

from datetime import date, datetime
from uuid import UUID

from drugtime.modules.identity.adapters.inbound.dependencies import (
    current_mobile_user,
    current_user,
    require_admin,
)
from drugtime.modules.identity.adapters.inbound.email_change_http import (
    get_email_change,
)
from drugtime.modules.identity.adapters.inbound.email_change_http import (
    router as email_change_router,
)
from drugtime.modules.identity.adapters.inbound.http import router
from drugtime.modules.identity.adapters.outbound.sql_device_tokens import SqlDeviceTokens
from drugtime.modules.identity.adapters.outbound.sql_email_change import SqlEmailChange
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
    "ProfileUpdateResult",
    "get_profile",
    "update_profile",
    "CurrentUser",
    "account_remover",
    "android_tokens",
    "remove_device_tokens",
    "current_user",
    "current_mobile_user",
    "eraser",
    "require_admin",
    "router",
    "user_name",
    "user_names",
    "user_emails",
    "user_exists",
    "verified_email",
    "email_change_applying",
    "reconcile_email_change",
]

router.include_router(email_change_router)


def email_change_applying(uow: UnitOfWork, user_id: UUID) -> bool:
    return SqlEmailChange().applying(uow, user_id)


def reconcile_email_change(user_id: UUID) -> None:
    """Trusted internal recovery; never expose this operation to app sessions."""
    get_email_change().reconcile(user_id)


def verified_email(user_id: UUID) -> str | None:
    return SupabaseAuth().verified_email(user_id)


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
    email: str | None = None,
    phone_number: str | None = None,
    at: datetime,
) -> _profile.ProfileUpdateResult:
    return _profile.update_profile(
        SqlUsers(uow),
        SupabaseAuth(),
        user_id,
        full_name=full_name,
        date_of_birth=date_of_birth,
        gender=gender,
        email=email,
        phone_number=phone_number,
        at=at,
    )


ProfileUpdateResult = _profile.ProfileUpdateResult


def user_emails(uow: UnitOfWork, user_ids: list[UUID]) -> dict[UUID, str | None]:
    """Email hiện tại của các user (None nếu đã xoá dữ liệu); id không tồn tại thì bị bỏ qua."""
    return SqlUsers(uow).emails(list(user_ids))


def android_tokens(uow: UnitOfWork, user_ids: list[UUID]) -> list[tuple[UUID, str]]:
    """Token FCM Android của các user (iOS bị bỏ qua: không có APNs trong Phase 1)."""
    return SqlUsers(uow).device_tokens(user_ids, "android")


def remove_device_tokens(uow: UnitOfWork, tokens: list[str]) -> None:
    """Gỡ token FCM mà kênh báo không còn đăng ký (UNREGISTERED), bất kể chủ sở hữu."""
    SqlDeviceTokens().remove_tokens(uow, tokens)


def user_name(uow: UnitOfWork, user_id: UUID) -> str | None:
    return SqlUsers(uow).user_name(user_id)


def user_names(uow: UnitOfWork, user_ids: list[UUID]) -> dict[UUID, str]:
    return SqlUsers(uow).user_names(user_ids)


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
