from typing import Protocol
from uuid import UUID

from drugtime.shared.uow import UnitOfWork


class Links(Protocol):
    def has_active_sharing_link(
        self, uow: UnitOfWork, patient_id: UUID, family_id: UUID
    ) -> bool: ...
    def sharing_family_ids(self, uow: UnitOfWork, patient_id: UUID) -> list[UUID]: ...
    def erase(self, uow: UnitOfWork, user_id: UUID) -> None: ...
