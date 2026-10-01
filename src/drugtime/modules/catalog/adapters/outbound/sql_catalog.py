from sqlalchemy import text

from drugtime.modules.catalog.domain.medication import CatalogMedication
from drugtime.shared.uow import UnitOfWork


class SqlCatalog:
    def get_medication(
        self, uow: UnitOfWork, medication_id: int, *, include_deleted: bool = False
    ) -> CatalogMedication | None:
        row = uow.connection.execute(
            text(
                "SELECT m.id, m.name, m.strength_text, m.dosage_form, "
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
        )
