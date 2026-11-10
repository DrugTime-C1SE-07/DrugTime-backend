from uuid import UUID

from drugtime.modules.family import api as family
from drugtime.modules.identity import api as identity
from drugtime.shared.uow import UnitOfWork


class LinkedPatientCandidates:
    def ids(self, uow: UnitOfWork, family_id: UUID) -> list[UUID]:
        return family.sharing_patient_ids(uow, family_id)


class LinkedPatientNames:
    def get(self, uow: UnitOfWork, patient_ids: list[UUID]) -> dict[UUID, str | None]:
        return identity.display_names(uow, patient_ids)


class LinkedPatientRequestAudit:
    def empty(self, uow: UnitOfWork, actor_id: UUID) -> None:
        family.audit_empty_patient_list(uow, actor_id)

    def denied(self, actor_id: UUID) -> None:
        family.audit_denied_patient_list(actor_id)
