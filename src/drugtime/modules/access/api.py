"""Giao diện công khai của access: điểm thực thi phân quyền duy nhất (CD1)."""

from uuid import UUID

from drugtime.modules.access.adapters.inbound.http import router
from drugtime.modules.access.adapters.outbound.facts import ModuleFactsReader
from drugtime.modules.access.adapters.outbound.sql_access_log import SqlAccessLog
from drugtime.modules.access.application import authorize as _authorize
from drugtime.modules.access.domain.rules import Scope
from drugtime.shared.uow import UnitOfWork

__all__ = ["Scope", "authorize", "authorized_caregivers", "router"]


def authorize(
    uow: UnitOfWork, *, caller_id: UUID, caller_is_admin: bool, patient_id: UUID, scope: Scope
) -> None:
    """Raise Forbidden nếu không có quyền; ghi access_logs khi cần."""
    _authorize.authorize(
        uow,
        ModuleFactsReader(),
        SqlAccessLog(),
        caller_id=caller_id,
        caller_is_admin=caller_is_admin,
        patient_id=patient_id,
        scope=scope,
    )


def authorized_caregivers(uow: UnitOfWork, patient_id: UUID) -> list[UUID]:
    return _authorize.authorized_caregivers(uow, ModuleFactsReader(), patient_id)
