from uuid import UUID

from sqlalchemy import text

from drugtime.modules.access.domain.rules import ActorRole, Scope
from drugtime.shared.db import unit_of_work
from drugtime.shared.uow import UnitOfWork

_INSERT = text(
    "INSERT INTO access_logs (actor_user_id, actor_role, patient_user_id, data_scope, result, "
    "rejection_reason, accessed_at) VALUES (:a, :r, :p, :s, :res, :reason, now())"
)


class SqlAccessLog:
    def append_allowed(
        self, uow: UnitOfWork, actor_id: UUID, role: ActorRole, patient_id: UUID, scope: Scope
    ) -> None:
        uow.connection.execute(
            _INSERT,
            {
                "a": actor_id,
                "r": str(role),
                "p": patient_id,
                "s": str(scope),
                "res": "allowed",
                "reason": None,
            },
        )

    def append_denied(
        self, actor_id: UUID, role: ActorRole, patient_id: UUID, scope: Scope, reason: str
    ) -> None:
        with unit_of_work() as own:  # transaction riêng
            own.connection.execute(
                _INSERT,
                {
                    "a": actor_id,
                    "r": str(role),
                    "p": patient_id,
                    "s": str(scope),
                    "res": "denied",
                    "reason": reason,
                },
            )
