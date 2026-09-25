from uuid import UUID

from sqlalchemy import text

from drugtime.modules.consent.domain.deletion_request import DeletionRequest, DeletionStatus
from drugtime.shared.uow import UnitOfWork


class SqlConsents:
    def has_active(self, uow: UnitOfWork, user_id: UUID, purpose: str) -> bool:
        return (
            uow.connection.execute(
                text(
                    "SELECT 1 FROM user_consents WHERE user_id = :u AND consent_type = :p "
                    "AND status = 'dong_y'"
                ),
                {"u": user_id, "p": purpose},
            ).first()
            is not None
        )


class SqlDeletionRequests:
    def get(self, uow: UnitOfWork, request_id: UUID) -> DeletionRequest | None:
        row = uow.connection.execute(
            text("SELECT id, user_id, status FROM data_deletion_requests WHERE id = :id"),
            {"id": request_id},
        ).first()
        return (
            None
            if row is None
            else DeletionRequest(row.id, row.user_id, DeletionStatus(row.status))
        )

    def approved_ids(self, uow: UnitOfWork) -> list[UUID]:
        rows = uow.connection.execute(
            text(
                "SELECT id FROM data_deletion_requests WHERE status = 'da_duyet' "
                "ORDER BY requested_at"
            )
        )
        return [r.id for r in rows]

    def mark_completed(self, uow: UnitOfWork, request_id: UUID) -> None:
        uow.connection.execute(
            text(
                "UPDATE data_deletion_requests SET status = 'hoan_tat', completed_at = now(), "
                "last_error = NULL WHERE id = :id AND status = 'da_duyet'"
            ),
            {"id": request_id},
        )

    def record_error(self, uow: UnitOfWork, request_id: UUID, error: str) -> None:
        uow.connection.execute(
            text("UPDATE data_deletion_requests SET last_error = :e WHERE id = :id"),
            {"id": request_id, "e": error[:1000]},
        )
