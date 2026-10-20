"""Adapter gọi module consent qua consent.api (task 3.13, BS-05)."""

from uuid import UUID

from drugtime.modules.consent import api as consent
from drugtime.shared.uow import UnitOfWork


class ConsentAdapter:
    def has_family_sharing(self, uow: UnitOfWork, user_id: UUID) -> bool:
        # Đọc DB ở mỗi request, không cache (bất biến 4).
        return consent.has_active_consent(uow, user_id, consent.Purpose.FAMILY_SHARING)
