"""Giao diện công khai của consent."""

from collections.abc import Sequence
from uuid import UUID

from drugtime.modules.consent.adapters.inbound.http import router
from drugtime.modules.consent.adapters.outbound.sql_consent import (
    SqlConsents,
    SqlDeletionRequests,
)
from drugtime.modules.consent.application import execute_erasure as _erasure
from drugtime.modules.consent.application.ports import AccountRemover, UserDataEraser
from drugtime.modules.consent.domain.consent import check_document_version
from drugtime.modules.consent.domain.purpose import Purpose
from drugtime.shared.uow import UnitOfWork

__all__ = [
    "check_document_version",
    "lock_active_consent",
    "AccountRemover",
    "Purpose",
    "UserDataEraser",
    "execute_erasure",
    "has_active_consent",
    "pending_erasure_ids",
    "router",
]


def has_active_consent(uow: UnitOfWork, user_id: UUID, purpose: Purpose | str) -> bool:
    return SqlConsents().has_active(uow, user_id, str(purpose))


def execute_erasure(
    request_id: UUID,
    *,
    erasers: Sequence[UserDataEraser],
    account_remover: AccountRemover,
    uow_factory,
) -> None:
    _erasure.execute_erasure(
        request_id,
        requests=SqlDeletionRequests(),
        erasers=erasers,
        account_remover=account_remover,
        uow_factory=uow_factory,
    )


def pending_erasure_ids(uow_factory) -> list[UUID]:
    return _erasure.pending_request_ids(SqlDeletionRequests(), uow_factory)


def lock_active_consent(uow: UnitOfWork, user_id: UUID, purpose: Purpose | str) -> bool:
    """Hold a SHARE lock on effective consent until the caller's transaction ends."""
    return SqlConsents().lock_active(uow, user_id, str(purpose))
