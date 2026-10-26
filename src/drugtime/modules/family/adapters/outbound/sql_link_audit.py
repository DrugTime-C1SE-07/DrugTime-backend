from uuid import UUID

from sqlalchemy import text

from drugtime.shared.db import unit_of_work
from drugtime.shared.uow import UnitOfWork

_INSERT = text(
    "INSERT INTO family_link_audit_events "
    "(actor_user_id, patient_user_id, link_id, operation, result, reason) "
    "VALUES (:a, :p, :l, :op, :result, :reason)"
)


class SqlLinkAudit:
    def allowed(
        self,
        uow: UnitOfWork,
        actor_id: UUID,
        patient_id: UUID,
        link_id: int | None,
        operation: str,
    ) -> None:
        uow.connection.execute(
            _INSERT,
            {
                "a": actor_id,
                "p": patient_id,
                "l": link_id,
                "op": operation,
                "result": "allowed",
                "reason": None,
            },
        )

    def denied(
        self,
        actor_id: UUID,
        patient_id: UUID | None,
        link_id: int | None,
        operation: str,
        reason: str,
    ) -> None:
        # Independent transaction: a rejected request must not roll back its audit.
        with unit_of_work() as own:
            own.connection.execute(
                _INSERT,
                {
                    "a": actor_id,
                    "p": patient_id,
                    "l": link_id,
                    "op": operation,
                    "result": "denied",
                    "reason": reason,
                },
            )
