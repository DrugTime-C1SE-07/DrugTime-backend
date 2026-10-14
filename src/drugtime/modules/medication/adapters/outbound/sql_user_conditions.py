from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from drugtime.modules.medication.domain.user_condition import NewUserCondition, UserConditionRecord
from drugtime.shared.errors import DomainError
from drugtime.shared.uow import UnitOfWork


def _record(row) -> UserConditionRecord | None:
    return None if row is None else UserConditionRecord(**dict(row._mapping))


class SqlUserConditions:
    def list(self, uow: UnitOfWork, user_id: UUID) -> list[UserConditionRecord]:
        rows = uow.connection.execute(
            text(
                "SELECT id, condition_id, subtype, stage FROM user_conditions "
                "WHERE user_id = :user_id ORDER BY id ASC"
            ),
            {"user_id": user_id},
        )
        return [UserConditionRecord(**dict(row._mapping)) for row in rows]

    def insert(
        self, uow: UnitOfWork, user_id: UUID, cmd: NewUserCondition
    ) -> UserConditionRecord | None:
        try:
            # A catalog deletion race must not leave the outer transaction aborted.
            with uow.connection.begin_nested():
                row = uow.connection.execute(
                    text(
                        "INSERT INTO user_conditions (user_id, condition_id, subtype, stage) "
                        "VALUES (:user_id, :condition_id, :subtype, :stage) "
                        "ON CONFLICT (user_id, condition_id) DO NOTHING "
                        "RETURNING id, condition_id, subtype, stage"
                    ),
                    {
                        "user_id": user_id,
                        "condition_id": cmd.condition_id,
                        "subtype": cmd.subtype,
                        "stage": cmd.stage,
                    },
                ).first()
        except IntegrityError as exc:
            diagnostic = getattr(exc.orig, "diag", None)
            if (
                getattr(exc.orig, "sqlstate", None) == "23503"
                and getattr(diagnostic, "constraint_name", None)
                == "user_conditions_condition_id_fkey"
            ):
                raise DomainError("condition_not_found") from exc
            raise
        return _record(row)

    def update(
        self, uow: UnitOfWork, user_id: UUID, link_id: int, fields: dict[str, str | None]
    ) -> UserConditionRecord | None:
        if not fields or not fields.keys() <= {"subtype", "stage"}:
            raise DomainError("invalid_condition_update")
        assignments = ", ".join(f"{key} = :{key}" for key in sorted(fields))
        row = uow.connection.execute(
            text(
                f"UPDATE user_conditions SET {assignments} "
                "WHERE id = :link_id AND user_id = :user_id "
                "RETURNING id, condition_id, subtype, stage"
            ),
            {**fields, "link_id": link_id, "user_id": user_id},
        ).first()
        return _record(row)

    def delete(self, uow: UnitOfWork, user_id: UUID, link_id: int) -> bool:
        return (
            uow.connection.execute(
                text(
                    "DELETE FROM user_conditions "
                    "WHERE id = :link_id AND user_id = :user_id RETURNING id"
                ),
                {"link_id": link_id, "user_id": user_id},
            ).first()
            is not None
        )
