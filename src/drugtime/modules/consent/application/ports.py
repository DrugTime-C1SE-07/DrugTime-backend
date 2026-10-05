from typing import Protocol
from uuid import UUID

from drugtime.modules.consent.domain.consent import ActiveConsent
from drugtime.modules.consent.domain.deletion_request import DeletionRequest
from drugtime.modules.consent.domain.purpose import Purpose
from drugtime.shared.uow import UnitOfWork


class UserDataEraser(Protocol):
    """Port do consent định nghĩa; mỗi module hiện thực và được inject ở worker (CD9).

    Nhờ port này consent gọi các module lúc chạy (W13–W18) mà KHÔNG import chúng,
    nên không có vòng phụ thuộc consent → adherence → access → consent.
    """

    name: str

    def erase_user(self, uow: UnitOfWork, user_id: UUID) -> None: ...


class AccountRemover(Protocol):
    def delete_account(self, user_id: UUID) -> None: ...


class DeletionRequests(Protocol):
    def get(self, uow: UnitOfWork, request_id: UUID) -> DeletionRequest | None: ...
    def approved_ids(self, uow: UnitOfWork) -> list[UUID]: ...
    def mark_completed(self, uow: UnitOfWork, request_id: UUID) -> None: ...
    def record_error(self, uow: UnitOfWork, request_id: UUID, error: str) -> None: ...


class ConsentReader(Protocol):
    def has_active(self, uow: UnitOfWork, user_id: UUID, purpose: str) -> bool: ...


class ConsentStore(Protocol):
    """user_consents chỉ ghi thêm: cấp là dòng mới, rút là đánh dấu dòng đang hiệu lực."""

    def active(self, uow: UnitOfWork, user_id: UUID) -> dict[Purpose, ActiveConsent]: ...

    def insert_active(
        self, uow: UnitOfWork, user_id: UUID, purpose: Purpose, document_version: str
    ) -> ActiveConsent | None:
        """None khi mục đích đó đã có consent hiệu lực (kể cả do request song song)."""
        ...

    def replace_active(
        self, uow: UnitOfWork, user_id: UUID, purpose: Purpose, document_version: str
    ) -> ActiveConsent | None:
        """Thu hồi dòng hiệu lực có phiên bản khác rồi ghi dòng mới, cùng transaction.

        None khi request song song đã thay trước (đã có dòng hiệu lực mới)."""
        ...

    def withdraw_active(self, uow: UnitOfWork, user_id: UUID, purpose: Purpose) -> None: ...
