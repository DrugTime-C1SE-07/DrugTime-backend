from __future__ import annotations

from sqlalchemy import text

from drugtime.modules.catalog.application.list_conditions import ConditionPage
from drugtime.modules.catalog.domain.condition import Condition
from drugtime.shared.uow import UnitOfWork


class SqlConditions:
    def list(self, uow: UnitOfWork, *, limit: int, offset: int) -> ConditionPage:
        total = uow.connection.execute(text("SELECT count(*) FROM conditions")).scalar_one()
        if offset >= total:
            return ConditionPage([], total)
        rows = uow.connection.execute(
            text("SELECT id, name FROM conditions ORDER BY id ASC LIMIT :limit OFFSET :offset"),
            {"limit": limit, "offset": offset},
        )
        return ConditionPage([Condition(*r) for r in rows], total)

    def get(self, uow: UnitOfWork, condition_id: int) -> Condition | None:
        row = uow.connection.execute(
            text("SELECT id, name FROM conditions WHERE id = :id"), {"id": condition_id}
        ).first()
        return None if row is None else Condition(*row)

    def names(self, uow: UnitOfWork, ids: list[int]) -> dict[int, str]:
        if not ids:
            return {}
        rows = uow.connection.execute(
            text("SELECT id, name FROM conditions WHERE id = ANY(:ids)"), {"ids": ids}
        )
        return {r.id: r.name for r in rows}
