from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from drugtime.modules.catalog.application.search_medications import escape_like
from drugtime.modules.catalog.domain.catalog_index import (
    CatalogHit,
    CatalogQueryResult,
    MatchKind,
)
from drugtime.modules.catalog.domain.medication import CatalogMedication
from drugtime.shared.errors import DomainError
from drugtime.shared.uow import UnitOfWork

_TABLE = "medications"


class SqlCatalog:
    # --- Dành cho tìm kiếm Mobile K04 & module khác ---
    def find_ocr_matches(
        self, uow: UnitOfWork, query_key: str, kind: MatchKind, *, limit: int = 200
    ) -> CatalogQueryResult:
        """Bound distinct IDs per source, retaining every alias hit for selected IDs."""
        if not query_key:
            return CatalogQueryResult(())
        if limit <= 0:
            raise ValueError("OCR candidate limit must be positive")
        columns = (
            "m.id, m.name, m.raw_active_ingredient, m.strength_text, m.dosage_form, "
            "EXISTS (SELECT 1 FROM medication_active_ingredients mai "
            "WHERE mai.medication_id = m.id) AS has_active_ingredients "
        )
        if kind == MatchKind.INGREDIENT_ALIAS:
            sql = (
                "WITH matched AS MATERIALIZED ("
                "SELECT a.id AS alias_id, a.alias_text, a.active_ingredient_id, m.id "
                "FROM ingredient_aliases a "
                "JOIN medication_active_ingredients mai "
                "ON mai.active_ingredient_id = a.active_ingredient_id "
                "JOIN medications m ON m.id = mai.medication_id "
                "WHERE m.deleted_at IS NULL "
                "AND public.catalog_search_key(a.alias_text) LIKE :pattern ESCAPE '\\'), "
                "selected AS (SELECT DISTINCT id FROM matched ORDER BY id LIMIT :probe) "
                "SELECT " + columns + ", h.alias_id, h.alias_text, h.active_ingredient_id "
                "FROM selected s JOIN medications m ON m.id = s.id "
                "JOIN matched h ON h.id = s.id ORDER BY m.id, h.alias_id"
            )
        else:
            # Only these fixed identifiers enter SQL; OCR text is always a bound value.
            column = {
                MatchKind.NAME: "m.name",
                MatchKind.RAW_ACTIVE_INGREDIENT: "m.raw_active_ingredient",
            }[kind]
            sql = (
                "SELECT " + columns + " FROM medications m WHERE m.deleted_at IS NULL "
                f"AND public.catalog_search_key({column}) LIKE :pattern ESCAPE '\\' "
                "ORDER BY m.id LIMIT :probe"
            )
        rows = uow.connection.execute(
            text(sql), {"pattern": f"%{escape_like(query_key)}%", "probe": limit + 1}
        )
        # Consume the iterator before returning, so any late read failure aborts the call.
        hits = tuple(
            CatalogHit(
                CatalogMedication(
                    row.id, row.name, row.strength_text, row.dosage_form,
                    row.has_active_ingredients, row.raw_active_ingredient,
                ),
                row.alias_id if kind == MatchKind.INGREDIENT_ALIAS else None,
                row.alias_text if kind == MatchKind.INGREDIENT_ALIAS else None,
                row.active_ingredient_id if kind == MatchKind.INGREDIENT_ALIAS else None,
            )
            for row in rows
        )
        selected_ids = sorted({hit.medication.id for hit in hits})
        truncated = len(selected_ids) > limit
        allowed = set(selected_ids[:limit])
        return CatalogQueryResult(
            tuple(hit for hit in hits if hit.medication.id in allowed), truncated
        )

    def get_medication(
        self, uow: UnitOfWork, medication_id: int, *, include_deleted: bool = False
    ) -> CatalogMedication | None:
        row = uow.connection.execute(
            text(
                "SELECT m.id, m.name, m.raw_active_ingredient, m.strength_text, m.dosage_form, "
                "EXISTS (SELECT 1 FROM medication_active_ingredients mai "
                "        WHERE mai.medication_id = m.id) AS has_active_ingredients "
                "FROM medications m "
                "WHERE m.id = :id AND (:include_deleted OR m.deleted_at IS NULL)"
            ),
            {"id": medication_id, "include_deleted": include_deleted},
        ).first()
        if row is None:
            return None
        return CatalogMedication(
            id=row.id,
            name=row.name,
            strength_text=row.strength_text,
            dosage_form=row.dosage_form,
            has_active_ingredients=row.has_active_ingredients,
            active_ingredient=row.raw_active_ingredient,
        )

    def search(self, uow: UnitOfWork, escaped: str, limit: int) -> list[CatalogMedication]:
        """`escaped`: chuỗi tìm đã escape `\\ % _` (xem search_medications). Cả hai phía so
        trên catalog_search_key (bỏ dấu, chữ thường), đúng biểu thức của index trigram."""
        c = uow.connection
        key = c.execute(
            text("SELECT public.catalog_search_key(:q)"), {"q": escaped}
        ).scalar_one()
        rows = c.execute(
            text(
                "SELECT m.id, m.name, m.raw_active_ingredient, m.strength_text, m.dosage_form, "
                "EXISTS (SELECT 1 FROM medication_active_ingredients mai "
                "        WHERE mai.medication_id = m.id) AS has_active_ingredients "
                "FROM medications m "
                "WHERE m.deleted_at IS NULL "
                "AND (public.catalog_search_key(m.name) LIKE :contains ESCAPE '\\' "
                "  OR public.catalog_search_key(m.raw_active_ingredient) LIKE :contains "
                "     ESCAPE '\\') "
                "ORDER BY (public.catalog_search_key(m.name) LIKE :prefix ESCAPE '\\') DESC, "
                "m.name, m.id "
                "LIMIT :limit"
            ),
            {"contains": f"%{key}%", "prefix": f"{key}%", "limit": limit},
        )
        return [
            CatalogMedication(
                id=r.id,
                name=r.name,
                strength_text=r.strength_text,
                dosage_form=r.dosage_form,
                has_active_ingredients=r.has_active_ingredients,
                active_ingredient=r.raw_active_ingredient,
            )
            for r in rows
        ]

    # --- Dành cho Admin CRUD PB04 ---
    def create(self, uow: UnitOfWork, data: dict) -> dict:
        try:
            row = uow.connection.execute(
                text(f"""
                    INSERT INTO {_TABLE}
                      (name, raw_active_ingredient, strength_text, dosage_form,
                       manufacturer_name, manufacturer_country, packaging_spec, source, source_ref)
                    VALUES
                      (:name, :raw_active_ingredient, :strength_text, :dosage_form,
                       :manufacturer_name, :manufacturer_country, :packaging_spec, :source, :source_ref)
                    RETURNING id, name, raw_active_ingredient, strength_text, dosage_form,
                              manufacturer_name, manufacturer_country, packaging_spec, source, source_ref, deleted_at
                """),
                data,
            ).mappings().one()
        except IntegrityError as exc:
            # UNIQUE(source, source_ref) hoặc CHECK pair
            raise DomainError("Duplicate source/source_ref or constraint violation") from exc
        return dict(row)

    def get_active(self, uow: UnitOfWork, med_id: int) -> dict | None:
        row = uow.connection.execute(
            text(f"SELECT * FROM {_TABLE} WHERE id = :id AND deleted_at IS NULL"),
            {"id": med_id},
        ).mappings().first()
        return dict(row) if row else None

    def list_active(
        self, uow: UnitOfWork, q: str | None, skip: int, limit: int
    ) -> tuple[list[dict], int]:
        where = "WHERE deleted_at IS NULL"
        params: dict = {}
        if q:
            where += " AND name ILIKE :q"
            params["q"] = f"%{q}%"
        total = uow.connection.execute(
            text(f"SELECT count(*) FROM {_TABLE} {where}"), params
        ).scalar_one()
        rows = uow.connection.execute(
            text(f"SELECT * FROM {_TABLE} {where} ORDER BY id OFFSET :skip LIMIT :limit"),
            {**params, "skip": skip, "limit": limit},
        ).mappings().all()
        return [dict(r) for r in rows], int(total)

    def update(self, uow: UnitOfWork, med_id: int, data: dict) -> dict | None:
        if not data:
            return self.get_active(uow, med_id)
        sets = ", ".join(f"{k} = :{k}" for k in data)
        try:
            row = uow.connection.execute(
                text(f"""
                    UPDATE {_TABLE} SET {sets}
                    WHERE id = :id AND deleted_at IS NULL
                    RETURNING *
                """),
                {"id": med_id, **data},
            ).mappings().first()
        except IntegrityError as exc:
            raise DomainError("Duplicate source/source_ref or constraint violation") from exc
        return dict(row) if row else None

    def soft_delete(self, uow: UnitOfWork, med_id: int) -> bool:
        row = uow.connection.execute(
            text(f"""
                UPDATE {_TABLE} SET deleted_at = now()
                WHERE id = :id AND deleted_at IS NULL
                RETURNING id
            """),
            {"id": med_id},
        ).first()
        return row is not None
