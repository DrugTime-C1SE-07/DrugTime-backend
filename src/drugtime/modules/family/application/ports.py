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
    def revoke(
        self,
        uow: UnitOfWork,
        *,
        link_id: int,
        caller_id: UUID,
        now: datetime,
    ) -> FamilyLink | None: ...
    def has_active_sharing_link(
        self, uow: UnitOfWork, patient_id: UUID, family_id: UUID
    ) -> bool: ...
    def sharing_family_ids(self, uow: UnitOfWork, patient_id: UUID) -> list[UUID]: ...
    def erase(self, uow: UnitOfWork, user_id: UUID) -> None: ...



class LinkCodes(Protocol):
    def find_by_patient(self, uow: UnitOfWork, patient_id: UUID) -> str | None:
        """Mã liên kết hiện có của user, hoặc None."""
        ...

    def insert_if_absent(self, uow: UnitOfWork, patient_id: UUID, code: str) -> str | None:
        """Ghi mã cho user nếu user chưa có mã.

        Trả mã đang lưu của user: mã vừa ghi, hoặc mã do request khác vừa tạo.
        Trả None khi `code` đã thuộc user khác (cần sinh mã mới).
        """
        ...
