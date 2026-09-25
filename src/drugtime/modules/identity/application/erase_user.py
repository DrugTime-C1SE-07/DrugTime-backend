from uuid import UUID

from drugtime.modules.identity.application.ports import AuthProvider, UserRepository


def erase_user(users: UserRepository, user_id: UUID) -> None:
    """Bước A (trong transaction): xóa device token, chuyển users thành tombstone."""
    users.erase(user_id)


def delete_account(auth: AuthProvider, user_id: UUID) -> None:
    """Bước B (ngoài transaction): xóa tài khoản Supabase Auth; idempotent."""
    auth.delete_account(user_id)
