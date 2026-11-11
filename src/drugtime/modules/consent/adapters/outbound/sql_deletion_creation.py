from dataclasses import asdict, fields
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from drugtime.modules.consent.domain.deletion_creation import DeletionOtpState, PendingDeletion
from drugtime.shared.errors import ServiceUnavailable
from drugtime.shared.uow import UnitOfWork

_OTP_COLUMNS = tuple(field.name for field in fields(DeletionOtpState))
_NAMES = ", ".join(_OTP_COLUMNS)
_VALUES = ", ".join(f":{name}" for name in _OTP_COLUMNS)
_UPDATES = ", ".join(f"{name} = EXCLUDED.{name}" for name in _OTP_COLUMNS)
_ACTIVE = "status IN ('cho_duyet', 'da_duyet') AND cancelled_at IS NULL"


class SqlDeletionCreation:
    def lock(self, uow: UnitOfWork, user_id: UUID) -> None:
        uow.connection.execute(text("SET LOCAL lock_timeout = '5s'"))
        try:
            uow.connection.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
                {"key": f"account-deletion:{user_id}"},
            )
        except DBAPIError as exc:
            if getattr(exc.orig, "sqlstate", None) == "55P03":
                raise ServiceUnavailable("service_unavailable") from None
            raise

    def otp_state(self, uow: UnitOfWork, user_id: UUID) -> DeletionOtpState:
        row = uow.connection.execute(
            text(f"SELECT {_NAMES} FROM deletion_otp_challenges WHERE user_id = :uid"),
            {"uid": user_id},
        ).mappings().one_or_none()
        return DeletionOtpState(**row) if row is not None else DeletionOtpState()

    def save_otp(self, uow: UnitOfWork, user_id: UUID, state: DeletionOtpState) -> None:
        uow.connection.execute(
            text(
                f"INSERT INTO deletion_otp_challenges (user_id, {_NAMES}) VALUES (:uid, {_VALUES}) "
                f"ON CONFLICT (user_id) DO UPDATE SET {_UPDATES}"
            ),
            {"uid": user_id, **asdict(state)},
        )

    def pending(self, uow: UnitOfWork, user_id: UUID) -> PendingDeletion | None:
        row = uow.connection.execute(
            text(
                "SELECT requested_at, scheduled_deletion_at FROM data_deletion_requests "
                f"WHERE user_id = :uid AND {_ACTIVE}"
            ),
            {"uid": user_id},
        ).one_or_none()
        return PendingDeletion(row.requested_at, row.scheduled_deletion_at) if row else None

    def insert(self, uow: UnitOfWork, user_id: UUID, request: PendingDeletion) -> None:
        uow.connection.execute(
            text(
                "INSERT INTO data_deletion_requests "
                "(user_id, status, requested_at, scheduled_deletion_at) "
                "VALUES (:uid, 'cho_duyet', :requested, :scheduled)"
            ),
            {
                "uid": user_id,
                "requested": request.requested_at,
                "scheduled": request.scheduled_deletion_at,
            },
        )
