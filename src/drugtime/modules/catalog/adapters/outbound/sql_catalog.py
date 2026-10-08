from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from drugtime.modules.catalog.domain.medication import CatalogMedication
from drugtime.shared.errors import DomainError
from drugtime.shared.uow import UnitOfWork

_TABLE = "medications"


class SqlCatalog:
    # --- Dành cho tìm kiếm Mobile K04 & module khác ---
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
