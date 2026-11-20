from collections.abc import Callable, Sequence
from contextlib import AbstractContextManager

from drugtime.modules.consent.application.ports import (
    AccountRemover,
    DeletionRequests,
    UserDataEraser,
)
from drugtime.shared.uow import UnitOfWork

UowFactory = Callable[[], AbstractContextManager[UnitOfWork]]


def execute_erasure(
    request_id: int,
    *,
    requests: DeletionRequests,
    erasers: Sequence[UserDataEraser],
    account_remover: AccountRemover,
    uow_factory: UowFactory,
) -> None:
    """CD9. Bước A: một transaction qua mọi eraser (thứ tự do composition root quyết định).
    Bước B: xóa tài khoản Auth. Chỉ đánh dấu hoàn tất khi cả hai xong. Idempotent."""
    try:
        with uow_factory() as uow:
            request = requests.get(uow, request_id)
            if request is None or not request.can_execute():
                return
            for eraser in erasers:
                eraser.erase_user(uow, request.user_id)
        account_remover.delete_account(request.user_id)
        with uow_factory() as uow:
            requests.mark_completed(uow, request_id)
    except Exception as exc:
        with uow_factory() as uow:
            requests.record_error(uow, request_id, type(exc).__name__)
        raise


def pending_request_ids(requests: DeletionRequests, uow_factory: UowFactory) -> list[int]:
    with uow_factory() as uow:
        return requests.approved_ids(uow)
