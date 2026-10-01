"""Adapter gọi module khác qua api.py (task 2.01)."""

from uuid import UUID

from drugtime.modules.access import api as access
from drugtime.modules.catalog import api as catalog
from drugtime.modules.medication.domain.user_medication import MedicationInfo
from drugtime.shared.uow import UnitOfWork


class AccessGuardAdapter:
    def _authorize(
        self,
        uow: UnitOfWork,
        caller_id: UUID,
        caller_is_admin: bool,
        patient_id: UUID,
        action: access.Action,
    ) -> None:
        access.authorize(
            uow,
            caller_id=caller_id,
            caller_is_admin=caller_is_admin,
            patient_id=patient_id,
            scope=access.Scope.MEDICATIONS,
            action=action,
        )

    def authorize_read(
        self, uow: UnitOfWork, caller_id: UUID, caller_is_admin: bool, patient_id: UUID
    ) -> None:
        self._authorize(uow, caller_id, caller_is_admin, patient_id, access.Action.READ)

    def authorize_write(
        self, uow: UnitOfWork, caller_id: UUID, caller_is_admin: bool, patient_id: UUID
    ) -> None:
        self._authorize(uow, caller_id, caller_is_admin, patient_id, access.Action.WRITE)


class CatalogAdapter:
    def get_medication(
        self, uow: UnitOfWork, medication_id: int, *, include_deleted: bool = False
    ) -> MedicationInfo | None:
        m = catalog.get_medication(uow, medication_id, include_deleted=include_deleted)
        if m is None:
            return None
        return MedicationInfo(
            id=m.id,
            name=m.name,
            strength_text=m.strength_text,
            dosage_form=m.dosage_form,
            has_active_ingredients=m.has_active_ingredients,
        )
