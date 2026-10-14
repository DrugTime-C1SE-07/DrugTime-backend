from uuid import UUID

from drugtime.modules.access.domain.rules import SCOPE_PURPOSE, AccessFacts, Scope
from drugtime.modules.consent import api as consent
from drugtime.modules.family import api as family
from drugtime.modules.identity import api as identity
from drugtime.shared.uow import UnitOfWork


class ModuleFactsReader:
    """Hiện thực FactsReader bằng cách gọi family.api, consent.api và identity.api (K19, K20)."""

    def read(
        self,
        uow: UnitOfWork,
        caller_id: UUID,
        caller_is_admin: bool,
        patient_id: UUID,
        scope: Scope,
    ) -> AccessFacts:
        is_self = caller_id == patient_id
        return AccessFacts(
            caller_id=caller_id,
            patient_id=patient_id,
            caller_is_admin=caller_is_admin,
            purpose_consent=consent.has_active_consent(uow, patient_id, SCOPE_PURPOSE[scope]),
            active_sharing_link=(not is_self)
            and family.has_active_sharing_link(uow, patient_id, caller_id),
            family_sharing_consent=(not is_self)
            and consent.has_active_consent(uow, patient_id, consent.Purpose.FAMILY_SHARING),
            patient_exists=is_self or identity.user_exists(uow, patient_id),
        )

    def sharing_family_ids(self, uow: UnitOfWork, patient_id: UUID) -> list[UUID]:
        return family.sharing_family_ids(uow, patient_id)

    def has_consent(self, uow: UnitOfWork, user_id: UUID, purpose: str) -> bool:
        return consent.has_active_consent(uow, user_id, purpose)
