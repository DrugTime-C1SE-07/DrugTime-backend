from uuid import UUID

from sqlalchemy import text

from drugtime.modules.identity.domain.user import RegistrationProfile, UserRecord
from drugtime.shared.uow import UnitOfWork


class SqlUsers:
    def __init__(self, uow: UnitOfWork) -> None:
        self._c = uow.connection

    def get(self, user_id: UUID) -> UserRecord | None:
        row = self._c.execute(
            text(
                "SELECT id, system_role, erased_at, full_name IS NOT NULL AS profile_complete "
                "FROM users WHERE id = :id"
            ),
            {"id": user_id},
        ).first()
        if row is None:
            return None
        return UserRecord(
            id=row.id,
            is_admin=row.system_role == "admin",
            erased=row.erased_at is not None,
            profile_complete=row.profile_complete,
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
            INSERT INTO users (id, full_name, date_of_birth, gender, phone_number, email)
            VALUES (:id, :full_name, :date_of_birth, :gender, :phone_number, :email)
            """),
            {
                "id": profile.id,
                "full_name": profile.full_name,
                "date_of_birth": profile.date_of_birth,
                "gender": profile.gender,
                "phone_number": profile.phone_number,
                "email": profile.email,
            },
        )

    def update_profile(
        self, user_id: UUID, *, full_name: str, date_of_birth, gender: str
    ) -> None:
        self._c.execute(
            text(
                "UPDATE users SET full_name = :full_name, date_of_birth = :dob, gender = :gender "
                "WHERE id = :id"
            ),
            {"full_name": full_name, "dob": date_of_birth, "gender": gender, "id": user_id},
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

