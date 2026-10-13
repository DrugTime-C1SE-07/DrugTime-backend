from datetime import datetime
from uuid import UUID

from sqlalchemy import text

from drugtime.modules.family.domain.link import FamilyLink, LinkStatus
from drugtime.shared.uow import UnitOfWork

_ACTIVE = "status = 'active' AND sharing_enabled = true"

_SELECT_BY_PAIR = text("""
SELECT id, patient_user_id, family_user_id, status, sharing_enabled,
       linked_at, revoked_at, rejected_at
FROM caregiver_links
WHERE patient_user_id = :patient_id AND family_user_id = :family_id
""")

_SELECT_BY_ID = text("""
SELECT id, patient_user_id, family_user_id, status, sharing_enabled,
       linked_at, revoked_at, rejected_at
FROM caregiver_links
WHERE id = :id
""")

_INSERT_LINK = text("""
INSERT INTO caregiver_links (patient_user_id, family_user_id, status, sharing_enabled)
VALUES (:patient_id, :family_id, :status, false)
RETURNING id, patient_user_id, family_user_id, status, sharing_enabled,
          linked_at, revoked_at, rejected_at
""")

_UPDATE_STATUS = text("""
UPDATE caregiver_links
SET status = :status,
    revoked_at = :revoked_at,
    rejected_at = :rejected_at
WHERE id = :id
RETURNING id, patient_user_id, family_user_id, status, sharing_enabled,
          linked_at, revoked_at, rejected_at
""")


class SqlLinks:
    def find_by_pair(
        self, uow: UnitOfWork, patient_id: UUID, family_id: UUID
    ) -> FamilyLink | None:
        row = uow.connection.execute(
            _SELECT_BY_PAIR, {"patient_id": patient_id, "family_id": family_id}
        ).first()
        return None if row is None else _record(row)

    def get(self, uow: UnitOfWork, link_id: int) -> FamilyLink | None:
        row = uow.connection.execute(_SELECT_BY_ID, {"id": link_id}).first()
        return None if row is None else _record(row)

    def create(self, uow: UnitOfWork, link: FamilyLink) -> FamilyLink:
        row = uow.connection.execute(
            _INSERT_LINK,
            {
                "patient_id": link.patient_user_id,
                "family_id": link.family_user_id,
                "status": link.status.value,
            },
        ).one()
        return _record(row)

    def update_status(
        self,
        uow: UnitOfWork,
        link_id: int,
        status: LinkStatus,
        revoked_at: datetime | None,
        rejected_at: datetime | None,
    ) -> FamilyLink:
        row = uow.connection.execute(
            _UPDATE_STATUS,
            {
                "id": link_id,
                "status": status.value,
                "revoked_at": revoked_at,
                "rejected_at": rejected_at,
            },
        ).one()
        return _record(row)

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


def _record(row) -> FamilyLink:
    return FamilyLink(
        id=row.id,
        patient_user_id=row.patient_user_id,
        family_user_id=row.family_user_id,
        status=LinkStatus(row.status),
        sharing_enabled=row.sharing_enabled,
        linked_at=row.linked_at,
        revoked_at=row.revoked_at,
        rejected_at=row.rejected_at,
    )
