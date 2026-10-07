from datetime import datetime
from typing import Protocol
from uuid import UUID

from drugtime.modules.family.domain.link import FamilyLink, LinkStatus
from drugtime.shared.uow import UnitOfWork


class Links(Protocol):
    def find_by_pair(
        self, uow: UnitOfWork, patient_id: UUID, family_id: UUID
    ) -> FamilyLink | None: ...
    def get(self, uow: UnitOfWork, link_id: int) -> FamilyLink | None: ...
    def create(self, uow: UnitOfWork, link: FamilyLink) -> FamilyLink: ...
    def update_status(
        self,
        uow: UnitOfWork,
        link_id: int,
        status: LinkStatus,
        revoked_at: datetime | None,
        rejected_at: datetime | None,
    ) -> FamilyLink: ...
    def has_active_sharing_link(
        self, uow: UnitOfWork, patient_id: UUID, family_id: UUID
    ) -> bool: ...
    def sharing_family_ids(self, uow: UnitOfWork, patient_id: UUID) -> list[UUID]: ...
    def erase(self, uow: UnitOfWork, user_id: UUID) -> None: ...
