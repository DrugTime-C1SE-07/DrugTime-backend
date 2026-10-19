from uuid import UUID

from drugtime.modules.consent import api as consent
from drugtime.modules.identity import api as identity
from drugtime.shared.uow import UnitOfWork


class SharingConsentGateway:
    def lock_active(self, uow: UnitOfWork, patient_id: UUID) -> bool:
        return consent.lock_active_consent(uow, patient_id, consent.Purpose.FAMILY_SHARING)

    def check_version(self, document_version: str) -> None:
        consent.check_document_version(consent.Purpose.FAMILY_SHARING, document_version)


class DisplayNamesGateway:
    def get(self, uow: UnitOfWork, user_ids: list[UUID]) -> dict[UUID, str | None]:
        return identity.display_names(uow, user_ids)
