from uuid import UUID

from drugtime.modules.consent.application.ports import ConsentStore
from drugtime.modules.consent.domain.consent import (
    ConsentState,
    check_document_version,
    check_withdrawable,
    grant_action,
    states_for,
)
from drugtime.modules.consent.domain.purpose import Purpose
from drugtime.shared.uow import UnitOfWork


def list_consents(uow: UnitOfWork, *, user_id: UUID, store: ConsentStore) -> list[ConsentState]:
    return states_for(store.active(uow, user_id))


def grant_consent(
    uow: UnitOfWork,
    *,
    user_id: UUID,
    purpose: Purpose,
    document_version: str,
    store: ConsentStore,
) -> tuple[ConsentState, bool]:
    """Đồng ý một mục đích. Trả (trạng thái, True nếu vừa ghi consent mới).

    Đã có consent hiệu lực thì trả consent đó, không ghi gì (gửi lại an toàn); riêng terms
    có phiên bản cũ thì được thay bằng phiên bản hiện hành."""
    check_document_version(purpose, document_version)
    action = grant_action(purpose, store.active(uow, user_id).get(purpose), document_version)
    if action == "insert":
        written = store.insert_active(uow, user_id, purpose, document_version)
    elif action == "replace":
        written = store.replace_active(uow, user_id, purpose, document_version)
    else:
        written = None
    if written is not None:
        return ConsentState(purpose, written), True
    existing = store.active(uow, user_id).get(purpose)
    if existing is None:
        raise LookupError("consent insert conflicted without an active row")
    return ConsentState(purpose, existing), False


def withdraw_consent(
    uow: UnitOfWork, *, user_id: UUID, purpose: Purpose, store: ConsentStore
) -> ConsentState:
    """Rút một mục đích; không có consent hiệu lực thì không làm gì. Terms không rút được."""
    check_withdrawable(purpose)
    store.withdraw_active(uow, user_id, purpose)
    return ConsentState(purpose, None)
