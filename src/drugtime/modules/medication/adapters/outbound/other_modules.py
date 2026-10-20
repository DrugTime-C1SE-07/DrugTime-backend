"""Adapter gọi module khác qua api.py (task 2.01)."""

from datetime import date, datetime
from uuid import UUID

from drugtime.modules.access import api as access
from drugtime.modules.catalog import api as catalog
from drugtime.modules.identity import api as identity
from drugtime.modules.medication.domain.user_condition import PersonalProfile
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
            active_ingredient=m.active_ingredient,
        )


class HealthProfileAccessAdapter:
    def authorize_read(self, uow: UnitOfWork, user_id: UUID, is_admin: bool) -> None:
        access.authorize(
            uow,
            caller_id=user_id,
            caller_is_admin=is_admin,
            patient_id=user_id,
            scope=access.Scope.HEALTH_PROFILE,
            action=access.Action.READ,
        )

    def authorize_write(self, uow: UnitOfWork, user_id: UUID, is_admin: bool) -> None:
        access.authorize(
            uow,
            caller_id=user_id,
            caller_is_admin=is_admin,
            patient_id=user_id,
            scope=access.Scope.HEALTH_PROFILE,
            action=access.Action.WRITE,
        )


class IdentityProfileAdapter:
    def get(self, uow: UnitOfWork, user_id: UUID) -> PersonalProfile:
        profile = identity.get_profile(uow, user_id)
        return PersonalProfile(
            profile.full_name,
            profile.date_of_birth,
            profile.gender,
            profile.email,
        )

    def update(
        self,
        uow: UnitOfWork,
        user_id: UUID,
        *,
        full_name: str,
        date_of_birth: date,
        gender: str,
        email: str | None,
        at: datetime,
    ) -> tuple[str | None, bool]:
        result = identity.update_profile(
            uow,
            user_id,
            full_name=full_name,
            date_of_birth=date_of_birth,
            gender=gender,
            email=email,
            at=at,
        )
        return result.previous_email, result.auth_email_changed


class ConditionCatalogAdapter:
    def get_name(self, uow: UnitOfWork, condition_id: int) -> str | None:
        condition = catalog.get_condition(uow, condition_id)
        return None if condition is None else condition.name

    def names(self, uow: UnitOfWork, ids: list[int]) -> dict[int, str]:
        return catalog.condition_names(uow, ids)
