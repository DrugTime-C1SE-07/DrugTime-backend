from datetime import datetime
from uuid import UUID

from sqlalchemy import text

from drugtime.modules.family.domain.link import FamilyLink, LinkStatus
from drugtime.shared.uow import UnitOfWork

_ACTIVE = "status = 'active' AND sharing_enabled = true"

_COLUMNS = """id, patient_user_id, family_user_id, status, sharing_enabled,
       linked_at, revoked_at, rejected_at, client_uuid"""

# Khóa theo người gửi, nhả khi transaction kết thúc (task 3.13, AC13).
_LOCK_SENDER = text(
    "SELECT pg_advisory_xact_lock("
    "hashtextextended('family_link_request:' || CAST(:family_id AS text), 0))"
)

_SELECT_BY_CLIENT_UUID = text(f"""
SELECT {_COLUMNS}
FROM caregiver_links
WHERE family_user_id = :family_id AND client_uuid = :client_uuid
""")

# Tối đa một dòng nhờ caregiver_links_one_open_pair_idx.
_SELECT_OPEN_BY_PAIR = text(f"""
SELECT {_COLUMNS}
FROM caregiver_links
WHERE patient_user_id = :patient_id AND family_user_id = :family_id
  AND status IN ('pending', 'active')
""")

_COUNT_CREATED_SINCE = text("""
SELECT count(*) FROM caregiver_links
WHERE family_user_id = :family_id AND linked_at >= :since
""")

# Chuỗi rejected liên tiếp gần nhất: các dòng rejected sau dòng không phải rejected cuối cùng.
# Dòng active/revoked (đã được chấp thuận) cắt chuỗi (BS-04).
_REJECTION_STREAK = text("""
SELECT count(*) AS streak, max(rejected_at) AS last_rejected_at
FROM caregiver_links
WHERE patient_user_id = :patient_id AND family_user_id = :family_id
  AND status = 'rejected'
  AND id > COALESCE((
      SELECT max(id) FROM caregiver_links
      WHERE patient_user_id = :patient_id AND family_user_id = :family_id
        AND status <> 'rejected'
  ), 0)
""")

_SELECT_BY_ID = text(f"""
SELECT {_COLUMNS}
FROM caregiver_links
WHERE id = :id
""")

_INSERT_LINK = text(f"""
INSERT INTO caregiver_links (patient_user_id, family_user_id, status, sharing_enabled, client_uuid)
VALUES (:patient_id, :family_id, :status, false, :client_uuid)
RETURNING {_COLUMNS}
""")

_UPDATE_STATUS = text(f"""
UPDATE caregiver_links
SET status = :status,
    revoked_at = :revoked_at,
    rejected_at = :rejected_at
WHERE id = :id
RETURNING {_COLUMNS}
""")


class SqlLinks:
    def lock_sender(self, uow: UnitOfWork, family_id: UUID) -> None:
        uow.connection.execute(_LOCK_SENDER, {"family_id": family_id})

    def find_by_client_uuid(
        self, uow: UnitOfWork, family_id: UUID, client_uuid: UUID
    ) -> FamilyLink | None:
        row = uow.connection.execute(
            _SELECT_BY_CLIENT_UUID, {"family_id": family_id, "client_uuid": client_uuid}
        ).first()
        return None if row is None else _record(row)

    def find_open_by_pair(
        self, uow: UnitOfWork, patient_id: UUID, family_id: UUID
    ) -> FamilyLink | None:
        row = uow.connection.execute(
            _SELECT_OPEN_BY_PAIR, {"patient_id": patient_id, "family_id": family_id}
        ).first()
        return None if row is None else _record(row)

    def count_created_since(self, uow: UnitOfWork, family_id: UUID, since: datetime) -> int:
        return uow.connection.execute(
            _COUNT_CREATED_SINCE, {"family_id": family_id, "since": since}
        ).scalar()

    def rejection_streak(
        self, uow: UnitOfWork, patient_id: UUID, family_id: UUID
    ) -> tuple[int, datetime | None]:
        row = uow.connection.execute(
            _REJECTION_STREAK, {"patient_id": patient_id, "family_id": family_id}
        ).one()
        return row.streak, row.last_rejected_at

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
                "client_uuid": link.client_uuid,
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
        c.execute(
            text("DELETE FROM link_request_attempts WHERE family_user_id = :u"), {"u": user_id}
        )


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
        client_uuid=row.client_uuid,
    )
