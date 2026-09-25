from uuid import UUID

from sqlalchemy import text

from drugtime.shared.uow import UnitOfWork

_ACTIVE = "status = 'active' AND sharing_enabled = true"


class SqlLinks:
    def has_active_sharing_link(self, uow: UnitOfWork, patient_id: UUID, family_id: UUID) -> bool:
        return (
            uow.connection.execute(
                text(
                    f"SELECT 1 FROM caregiver_links WHERE patient_user_id = :p "
                    f"AND family_user_id = :f AND {_ACTIVE}"
                ),
                {"p": patient_id, "f": family_id},
            ).first()
            is not None
        )

    def sharing_family_ids(self, uow: UnitOfWork, patient_id: UUID) -> list[UUID]:
        rows = uow.connection.execute(
            text(
                f"SELECT family_user_id FROM caregiver_links WHERE patient_user_id = :p "
                f"AND {_ACTIVE}"
            ),
            {"p": patient_id},
        )
        return [r.family_user_id for r in rows]

    def erase(self, uow: UnitOfWork, user_id: UUID) -> None:
        c = uow.connection
        c.execute(
            text("DELETE FROM caregiver_links WHERE patient_user_id = :u OR family_user_id = :u"),
            {"u": user_id},
        )
        c.execute(text("DELETE FROM link_codes WHERE patient_user_id = :u"), {"u": user_id})
        c.execute(
            text("UPDATE link_codes SET family_user_id = NULL WHERE family_user_id = :u"),
            {"u": user_id},
        )
