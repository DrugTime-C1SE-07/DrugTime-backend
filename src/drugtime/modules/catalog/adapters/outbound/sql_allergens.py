from __future__ import annotations

from sqlalchemy import text

from drugtime.modules.catalog.domain.allergen import Allergen
from drugtime.shared.uow import UnitOfWork

_COLUMNS = "id, category, name, display_order, is_active"


class SqlAllergens:
    def list_active(self, uow: UnitOfWork) -> list[Allergen]:
        """Active entries: drug before food, then catalog display order, then id."""
        rows = uow.connection.execute(
            text(
                f"SELECT {_COLUMNS} FROM allergens WHERE is_active "
                "ORDER BY CASE category WHEN 'drug' THEN 0 ELSE 1 END, display_order, id"
            )
        )
        return [Allergen(*row) for row in rows]

    def active_ids(self, uow: UnitOfWork, ids: list[str]) -> set[str]:
        if not ids:
            return set()
        rows = uow.connection.execute(
            text("SELECT id FROM allergens WHERE is_active AND id = ANY(:ids)"),
            {"ids": list(ids)},
        )
        return {row.id for row in rows}

    def labels(self, uow: UnitOfWork, ids: list[str]) -> dict[str, Allergen]:
        """Catalog entries by id, retired ones included; unknown ids are omitted."""
        if not ids:
            return {}
        rows = uow.connection.execute(
            text(f"SELECT {_COLUMNS} FROM allergens WHERE id = ANY(:ids)"),
            {"ids": list(ids)},
        )
        return {row.id: Allergen(*row) for row in rows}
