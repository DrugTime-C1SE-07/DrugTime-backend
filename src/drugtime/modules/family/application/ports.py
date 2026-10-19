from datetime import datetime
from typing import Protocol
from uuid import UUID

from drugtime.modules.family.domain.link import FamilyLink, LinkStatus
from drugtime.modules.family.domain.link_request import LinkRequestLimits
from drugtime.modules.family.domain.throttle import ThrottleState
from drugtime.shared.uow import UnitOfWork


class Links(Protocol):
    def lock_sender(self, uow: UnitOfWork, family_id: UUID) -> None:
        """Tuần tự hóa mọi yêu cầu liên kết của một người gửi tới hết transaction."""
        ...

    def find_by_client_uuid(
        self, uow: UnitOfWork, family_id: UUID, client_uuid: UUID
    ) -> FamilyLink | None: ...
    def find_open_by_pair(
        self, uow: UnitOfWork, patient_id: UUID, family_id: UUID
    ) -> FamilyLink | None:
        """Dòng pending/active của cặp (tối đa một, nhờ unique index một phần)."""
        ...

    def count_created_since(self, uow: UnitOfWork, family_id: UUID, since: datetime) -> int: ...
    def rejection_streak(
        self, uow: UnitOfWork, patient_id: UUID, family_id: UUID
    ) -> tuple[int, datetime | None]:
        """Số lần bị từ chối liên tiếp gần nhất của cặp và thời điểm từ chối cuối (BS-04)."""
        ...

    def get(self, uow: UnitOfWork, link_id: int) -> FamilyLink | None: ...
    def create(self, uow: UnitOfWork, link: FamilyLink) -> FamilyLink:
        """Ghi `link` (kèm `link.client_uuid` nếu có)."""
        ...

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


class LinkCodes(Protocol):
    def find_by_patient(self, uow: UnitOfWork, patient_id: UUID) -> str | None:
        """Mã liên kết hiện có của user, hoặc None."""
        ...

    def find_owner(self, uow: UnitOfWork, code: str) -> UUID | None:
        """Chủ của mã, hoặc None."""
        ...

    def insert_if_absent(self, uow: UnitOfWork, patient_id: UUID, code: str) -> str | None:
        """Ghi mã cho user nếu user chưa có mã.

        Trả mã đang lưu của user: mã vừa ghi, hoặc mã do request khác vừa tạo.
        Trả None khi `code` đã thuộc user khác (cần sinh mã mới).
        """
        ...


class LinkAttempts(Protocol):
    def state(
        self,
        uow: UnitOfWork,
        family_id: UUID,
        client_uuid: UUID,
        now: datetime,
        limits: LinkRequestLimits,
    ) -> ThrottleState:
        """Số lần sai của người gửi trong cửa sổ `limits.fail_window` tính tới `now`, khóa còn
        hiệu lực tại `now`, và `client_uuid` đã từng được tính lần sai hay chưa."""
        ...

    def record_failure(
        self,
        family_id: UUID,
        client_uuid: UUID,
        attempted_at: datetime,
        locked_until: datetime | None,
    ) -> None:
        """Ghi một lần sai ở transaction RIÊNG, để không mất khi request rollback vì trả 404.

        Một `client_uuid` chỉ được ghi một lần. Không nhận mã đã thử.
        """
        ...


class Consents(Protocol):
    def has_family_sharing(self, uow: UnitOfWork, user_id: UUID) -> bool: ...
