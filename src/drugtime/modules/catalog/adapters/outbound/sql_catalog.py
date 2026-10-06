from sqlalchemy import text

from drugtime.modules.catalog.domain.medication import CatalogMedication
from drugtime.shared.uow import UnitOfWork


class SqlCatalog:
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
        # Tính khóa trước rồi bind vào truy vấn chính: planner thấy mẫu LIKE cụ thể nên dùng
        # được index (mẫu lấy từ subquery thì không).
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
