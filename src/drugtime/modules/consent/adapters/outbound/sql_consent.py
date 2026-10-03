from uuid import UUID

from sqlalchemy import text

from drugtime.modules.consent.domain.consent import ActiveConsent
from drugtime.modules.consent.domain.deletion_request import DeletionRequest, DeletionStatus
from drugtime.modules.consent.domain.purpose import Purpose
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

    def active(self, uow: UnitOfWork, user_id: UUID) -> dict[Purpose, ActiveConsent]:
        rows = uow.connection.execute(
            text(
                "SELECT consent_type::text AS purpose, consented_at, document_version "
                "FROM user_consents WHERE user_id = :u AND status = 'dong_y'"
            ),
            {"u": user_id},
        )
        return {Purpose(r.purpose): ActiveConsent(r.consented_at, r.document_version) for r in rows}

    def insert_active(
        self, uow: UnitOfWork, user_id: UUID, purpose: Purpose, document_version: str
    ) -> ActiveConsent | None:
        # Partial unique index user_consents_one_active_idx: tối đa một dòng dong_y cho mỗi
        # (user_id, consent_type), nên request song song không tạo dòng thứ hai.
        row = uow.connection.execute(
            text(
                "INSERT INTO user_consents (user_id, consent_type, status, document_version) "
                "VALUES (:u, CAST(:p AS consent_type), 'dong_y', :v) "
                "ON CONFLICT (user_id, consent_type) WHERE status = 'dong_y' DO NOTHING "
                "RETURNING consented_at, document_version"
            ),
            {"u": user_id, "p": str(purpose), "v": document_version},
        ).first()
        return None if row is None else ActiveConsent(row.consented_at, row.document_version)

    def withdraw_active(self, uow: UnitOfWork, user_id: UUID, purpose: Purpose) -> None:
        # Không dùng now(): đó là thời điểm bắt đầu transaction, có thể sớm hơn consented_at của
        # dòng vừa được một request cấp song song commit → vi phạm CHECK revoked_at >= consented_at.
        uow.connection.execute(
            text(
                "UPDATE user_consents SET status = 'thu_hoi', "
                "revoked_at = GREATEST(clock_timestamp(), consented_at) "
                "WHERE user_id = :u AND consent_type = CAST(:p AS consent_type) "
                "AND status = 'dong_y'"
            ),
            {"u": user_id, "p": str(purpose)},
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
