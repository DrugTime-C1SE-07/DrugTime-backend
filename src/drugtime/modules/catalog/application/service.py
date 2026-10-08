from drugtime.modules.catalog.adapters.inbound.schemas import (
    MedicationCreate,
    MedicationUpdate,
)
from drugtime.modules.catalog.adapters.outbound.sql_catalog import SqlCatalog
from drugtime.shared.errors import NotFound
from drugtime.shared.uow import UnitOfWork


class CatalogService:
    def __init__(self, uow: UnitOfWork) -> None:
        self.uow = uow
        self.repo = SqlCatalog()

    def create(self, payload: MedicationCreate) -> dict:
        return self.repo.create(self.uow, payload.model_dump())

    def get(self, med_id: int) -> dict:
        row = self.repo.get_active(self.uow, med_id)
        if row is None:
            raise NotFound("Medication not found")
        return row

    def list(self, q: str | None, skip: int, limit: int) -> tuple[list[dict], int]:
        return self.repo.list_active(self.uow, q, skip, limit)

    def update(self, med_id: int, payload: MedicationUpdate) -> dict:
        data = payload.model_dump(exclude_unset=True)
        row = self.repo.update(self.uow, med_id, data)
        if row is None:
            raise NotFound("Medication not found")
        return row

    def soft_delete(self, med_id: int) -> None:
        ok = self.repo.soft_delete(self.uow, med_id)
        if not ok:
            raise NotFound("Medication not found")
