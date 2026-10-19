from uuid import UUID

from sqlalchemy import text

from drugtime.modules.identity.domain.profile import ProfileRecord
from drugtime.modules.identity.domain.user import UserRecord
from drugtime.shared.errors import Unauthorized
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

    def get_profile(self, user_id: UUID) -> ProfileRecord | None:
        row = self._c.execute(
            text(
                "SELECT full_name, date_of_birth, gender FROM users "
                "WHERE id = :id AND erased_at IS NULL"
            ),
            {"id": user_id},
        ).first()
        return None if row is None else ProfileRecord(*row)

    def update_profile(self, user_id: UUID, *, full_name: str, date_of_birth, gender: str) -> None:
        result = self._c.execute(
            text(
                "UPDATE users SET full_name = :full_name, date_of_birth = :dob, gender = :gender "
                "WHERE id = :id AND erased_at IS NULL"
            ),
            {"full_name": full_name, "dob": date_of_birth, "gender": gender, "id": user_id},
        )
        if result.rowcount != 1:
            raise Unauthorized("Account does not exist or has been deleted")

    def device_tokens(self, user_ids: list[UUID], platform: str) -> list[tuple[UUID, str]]:
        rows = self._c.execute(
            text(
                "SELECT user_id, fcm_token FROM device_tokens "
                "WHERE user_id = ANY(:ids) AND platform = :platform"
            ),
            {"ids": user_ids, "platform": platform},
        )
        return [(r.user_id, r.fcm_token) for r in rows]

    def user_name(self, user_id: UUID) -> str | None:
        row = self._c.execute(
            text("SELECT full_name FROM users WHERE id = :id AND erased_at IS NULL"),
            {"id": user_id},
        ).first()
        return None if row is None else row.full_name

    def user_names(self, user_ids: list[UUID]) -> dict[UUID, str]:
        if not user_ids:
            return {}
        rows = self._c.execute(
            text("SELECT id, full_name FROM users WHERE id = ANY(:ids) AND erased_at IS NULL"),
            {"ids": user_ids},
        )
        return {r.id: r.full_name for r in rows if r.full_name}

    def emails(self, user_ids: list[UUID]) -> dict[UUID, str | None]:
        if not user_ids:
            return {}
        rows = self._c.execute(
            text("SELECT id, email FROM users WHERE id = ANY(:ids)"), {"ids": user_ids}
        )
        return {r.id: r.email for r in rows}

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
