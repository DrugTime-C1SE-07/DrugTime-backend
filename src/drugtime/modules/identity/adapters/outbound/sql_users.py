from uuid import UUID

from sqlalchemy import text

from drugtime.modules.identity.domain.user import RegistrationProfile, UserRecord
from drugtime.shared.uow import UnitOfWork


class SqlUsers:
    def __init__(self, uow: UnitOfWork) -> None:
        self._c = uow.connection

    def get(self, user_id: UUID) -> UserRecord | None:
        row = self._c.execute(
            text("SELECT id, system_role, erased_at FROM users WHERE id = :id"), {"id": user_id}
        ).first()
        if row is None:
            return None
        return UserRecord(
            id=row.id, is_admin=row.system_role == "admin", erased=row.erased_at is not None
        )

    def create_minimal(self, user_id: UUID, *, phone: str | None, email: str | None) -> None:
        self._c.execute(
            text(
                "INSERT INTO users (id, phone_number, email) VALUES (:id, :phone, :email) "
                "ON CONFLICT (id) DO NOTHING"
            ),
            {"id": user_id, "phone": phone, "email": email},
        )

    def create_registered_user(self, profile: RegistrationProfile) -> None:
        self._c.execute(
            text("""
            INSERT INTO users (
                ho_ten, ngay_sinh, gioi_tinh, so_dien_thoai, vai_tro
            )
            VALUES (
                :ho_ten, :ngay_sinh, :gioi_tinh, :so_dien_thoai, :vai_tro
            )
            """),
            {
                "ho_ten": profile.full_name,
                "ngay_sinh": profile.date_of_birth,
                "gioi_tinh": profile.gender,
                "so_dien_thoai": profile.phone_number,
                "vai_tro": _account_type_to_db(profile.account_type),
            },
        )

    def device_tokens(self, user_ids: list[UUID], platform: str) -> list[tuple[UUID, str]]:
        rows = self._c.execute(
            text(
                "SELECT user_id, fcm_token FROM device_tokens "
                "WHERE user_id = ANY(:ids) AND platform = :platform"
            ),
            {"ids": user_ids, "platform": platform},
        )
        return [(r.user_id, r.fcm_token) for r in rows]

    def erase(self, user_id: UUID) -> None:
        self._c.execute(text("DELETE FROM device_tokens WHERE user_id = :u"), {"u": user_id})
        self._c.execute(
            text(
                "UPDATE users SET full_name = NULL, date_of_birth = NULL, gender = NULL, "
                "email = NULL, phone_number = NULL, erased_at = now() "
                "WHERE id = :u AND erased_at IS NULL"
            ),
            {"u": user_id},
        )


def _account_type_to_db(account_type) -> str:
    return {
        "patient": "Patient",
        "family_member": "Family Member",
    }[str(account_type)]
