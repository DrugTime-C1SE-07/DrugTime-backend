"""Giao diện công khai của family."""

from uuid import UUID

from drugtime.modules.family.adapters.inbound.http import router
from drugtime.modules.family.adapters.outbound.sql_links import SqlLinks
from drugtime.shared.uow import UnitOfWork

__all__ = ["eraser", "has_active_sharing_link", "router", "sharing_family_ids"]


def has_active_sharing_link(uow: UnitOfWork, patient_id: UUID, family_id: UUID) -> bool:
    return SqlLinks().has_active_sharing_link(uow, patient_id, family_id)


def sharing_family_ids(uow: UnitOfWork, patient_id: UUID) -> list[UUID]:
    return SqlLinks().sharing_family_ids(uow, patient_id)


class _Eraser:
    name = "family"

    def erase_user(self, uow: UnitOfWork, user_id: UUID) -> None:
        SqlLinks().erase(uow, user_id)


eraser = _Eraser()
