"""Hoạt chất chuẩn, tên gọi khác và liên kết thuốc–hoạt chất (task 2.16)."""

from sqlalchemy import text

from drugtime.modules.catalog.application.list_active_ingredients import (
    ActiveIngredient,
    ActiveIngredientPage,
)
from drugtime.shared.uow import UnitOfWork

# Khớp một phần, không phân biệt hoa thường, trên tên chuẩn hoặc alias. `:pattern` đã escape.
_MATCH = (
    "(ai.standard_name ILIKE :pattern ESCAPE '\\' OR EXISTS ("
    "SELECT 1 FROM ingredient_aliases al WHERE al.active_ingredient_id = ai.id "
    "AND al.alias_text ILIKE :pattern ESCAPE '\\'))"
)
_OF_MEDICATION = (
    "EXISTS (SELECT 1 FROM medication_active_ingredients mai "
    "WHERE mai.active_ingredient_id = ai.id AND mai.medication_id = :medication_id)"
)


class SqlActiveIngredients:
    def existing_ids(self, uow: UnitOfWork, ids: list[int]) -> set[int]:
        if not ids:
            return set()
        rows = uow.connection.execute(
            text("SELECT id FROM active_ingredients WHERE id = ANY(:ids)"), {"ids": list(ids)}
        )
        return {r.id for r in rows}

    def names(self, uow: UnitOfWork, ids: list[int]) -> dict[int, str]:
        if not ids:
            return {}
        rows = uow.connection.execute(
            text("SELECT id, standard_name FROM active_ingredients WHERE id = ANY(:ids)"),
            {"ids": list(ids)},
        )
        return {r.id: r.standard_name for r in rows}

    def ids_matching(self, uow: UnitOfWork, escaped: str) -> list[int]:
        rows = uow.connection.execute(
            text(f"SELECT ai.id FROM active_ingredients ai WHERE {_MATCH}"),
            {"pattern": f"%{escaped}%"},
        )
        return [r.id for r in rows]

    def ids_of_medication(self, uow: UnitOfWork, medication_id: int) -> list[int]:
        rows = uow.connection.execute(
            text(
                "SELECT active_ingredient_id FROM medication_active_ingredients "
                "WHERE medication_id = :m"
            ),
            {"m": medication_id},
        )
        return [r.active_ingredient_id for r in rows]

    def list(
        self,
        uow: UnitOfWork,
        *,
        escaped: str | None,
        medication_id: int | None,
        skip: int,
        limit: int,
    ) -> ActiveIngredientPage:
        where, params = ["TRUE"], {}
        if escaped is not None:
            where.append(_MATCH)
            params["pattern"] = f"%{escaped}%"
        if medication_id is not None:
            where.append(_OF_MEDICATION)
            params["medication_id"] = medication_id
        cond = " AND ".join(where)
        c = uow.connection
        total = c.execute(
            text(f"SELECT count(*) FROM active_ingredients ai WHERE {cond}"), params
        ).scalar_one()
        rows = c.execute(
            text(
                "SELECT ai.id, ai.standard_name, ai.atc_code, ai.pharmacological_group, "
                "COALESCE((SELECT array_agg(al.alias_text ORDER BY al.alias_text) "
                "  FROM ingredient_aliases al WHERE al.active_ingredient_id = ai.id), "
                "  ARRAY[]::text[]) AS aliases "
                f"FROM active_ingredients ai WHERE {cond} "
                "ORDER BY ai.standard_name, ai.id OFFSET :skip LIMIT :limit"
            ),
            {**params, "skip": skip, "limit": limit},
        )
        items = [
            ActiveIngredient(
                id=r.id,
                standard_name=r.standard_name,
                atc_code=r.atc_code,
                pharmacological_group=r.pharmacological_group,
                aliases=list(r.aliases),
            )
            for r in rows
        ]
        return ActiveIngredientPage(items=items, total=int(total))
