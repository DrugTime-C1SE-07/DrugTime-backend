from uuid import UUID

from drugtime.modules.consent.application.ports import ConsentStore
from drugtime.modules.consent.domain.consent import (
    ConsentState,
    check_document_version,
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

    Đã có consent hiệu lực thì trả consent đó, không ghi gì (gửi lại an toàn)."""
    check_document_version(purpose, document_version)
    inserted = store.insert_active(uow, user_id, purpose, document_version)
    if inserted is not None:
        return ConsentState(purpose, inserted), True
    existing = store.active(uow, user_id).get(purpose)
    if existing is None:
        raise LookupError("consent insert conflicted without an active row")
    return ConsentState(purpose, existing), False


def withdraw_consent(
    uow: UnitOfWork, *, user_id: UUID, purpose: Purpose, store: ConsentStore
) -> ConsentState:
    """Rút một mục đích; không có consent hiệu lực thì không làm gì."""
    store.withdraw_active(uow, user_id, purpose)
    return ConsentState(purpose, None)
