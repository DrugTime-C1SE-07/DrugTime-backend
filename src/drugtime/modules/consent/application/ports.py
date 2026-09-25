from typing import Protocol
from uuid import UUID

from drugtime.modules.consent.domain.deletion_request import DeletionRequest
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
