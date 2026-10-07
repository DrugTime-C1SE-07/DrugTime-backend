"""Giao diện công khai của family."""

from datetime import datetime
from uuid import UUID

from drugtime.modules.family.adapters.inbound.http import router
from drugtime.modules.family.adapters.outbound.sql_links import SqlLinks
from drugtime.modules.family.application import manage_links
from drugtime.modules.family.domain.link import FamilyLink
from drugtime.shared.uow import UnitOfWork

__all__ = [
    "approve_link",
    "create_link_request",
    "eraser",
    "has_active_sharing_link",
    "reject_link",
    "revoke_link",
    "router",
    "sharing_family_ids",
]


def create_link_request(uow: UnitOfWork, patient_id: UUID, family_id: UUID) -> FamilyLink:
    return manage_links.create_link_request(
        uow, patient_id=patient_id, family_id=family_id, links=SqlLinks()
    )


def approve_link(uow: UnitOfWork, link_id: int, now: datetime) -> FamilyLink:
    return manage_links.approve_link(uow, link_id=link_id, now=now, links=SqlLinks())


def revoke_link(uow: UnitOfWork, link_id: int, now: datetime) -> FamilyLink:
    return manage_links.revoke_link(uow, link_id=link_id, now=now, links=SqlLinks())


def reject_link(uow: UnitOfWork, link_id: int, now: datetime) -> FamilyLink:
    return manage_links.reject_link(uow, link_id=link_id, now=now, links=SqlLinks())


def has_active_sharing_link(uow: UnitOfWork, patient_id: UUID, family_id: UUID) -> bool:
    return SqlLinks().has_active_sharing_link(uow, patient_id, family_id)


def sharing_family_ids(uow: UnitOfWork, patient_id: UUID) -> list[UUID]:
    return SqlLinks().sharing_family_ids(uow, patient_id)


class _Eraser:
    name = "family"

    def erase_user(self, uow: UnitOfWork, user_id: UUID) -> None:
        SqlLinks().erase(uow, user_id)


eraser = _Eraser()
