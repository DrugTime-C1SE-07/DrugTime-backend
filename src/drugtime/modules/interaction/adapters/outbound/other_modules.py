"""Adapter gọi module khác qua api.py (task 2.16, 4.05)."""

from uuid import UUID

from drugtime.modules.catalog import api as catalog
from drugtime.modules.identity import api as identity
from drugtime.modules.medication import api as medication
from drugtime.shared.uow import UnitOfWork


class PatientMedications:
    """Thuốc của người bệnh; người gọi phải kiểm quyền trước (task 4.05)."""

    def active(self, uow: UnitOfWork, patient_id: UUID) -> list[medication.PatientMedicationRef]:
        return medication.patient_medication_refs(uow, patient_id)

    def one(
        self, uow: UnitOfWork, patient_id: UUID, user_medication_id: int
    ) -> medication.PatientMedicationRef | None:
        return medication.patient_medication_ref(uow, patient_id, user_medication_id)


class CatalogMedications:
    def get(self, uow: UnitOfWork, medication_id: int):
        # Thuốc người bệnh đang dùng vẫn được đối chiếu khi danh mục đã xoá mềm (G16).
        return catalog.get_medication(uow, medication_id, include_deleted=True)


class CatalogIngredients:
    def existing_ids(self, uow: UnitOfWork, ids: list[int]) -> set[int]:
        return catalog.existing_ingredient_ids(uow, ids)

    def names(self, uow: UnitOfWork, ids: list[int]) -> dict[int, str]:
        return catalog.ingredient_names(uow, ids)

    def ids_matching(self, uow: UnitOfWork, q: str) -> list[int]:
        return catalog.ingredient_ids_matching(uow, q)

    def ids_of_medication(self, uow: UnitOfWork, medication_id: int) -> list[int]:
        return catalog.ingredient_ids_of_medication(uow, medication_id)


class IdentityAdmins:
    def emails(self, uow: UnitOfWork, user_ids: list[UUID]) -> dict[UUID, str | None]:
        return identity.user_emails(uow, user_ids)
