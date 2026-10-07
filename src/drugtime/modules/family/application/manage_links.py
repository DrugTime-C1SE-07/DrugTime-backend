from datetime import datetime
from uuid import UUID

from drugtime.modules.family.application.ports import Links
from drugtime.modules.family.domain.link import (
    FamilyLink,
    LinkStatus,
    ensure_can_create_link,
    pending_link,
    transition_link,
)
from drugtime.shared.errors import NotFound
from drugtime.shared.uow import UnitOfWork


def create_link_request(
    uow: UnitOfWork, *, patient_id: UUID, family_id: UUID, links: Links
) -> FamilyLink:
    existing = links.find_by_pair(uow, patient_id, family_id)
    ensure_can_create_link(patient_id, family_id, existing)
    return links.create(uow, pending_link(patient_id, family_id))


def approve_link(uow: UnitOfWork, *, link_id: int, now: datetime, links: Links) -> FamilyLink:
    link = _get_link(uow, links, link_id)
    updated = transition_link(link, LinkStatus.ACTIVE, now=now)
    return links.update_status(
        uow, link_id, updated.status, updated.revoked_at, updated.rejected_at
    )


def revoke_link(uow: UnitOfWork, *, link_id: int, now: datetime, links: Links) -> FamilyLink:
    link = _get_link(uow, links, link_id)
    updated = transition_link(link, LinkStatus.REVOKED, now=now)
    return links.update_status(
        uow, link_id, updated.status, updated.revoked_at, updated.rejected_at
    )


def reject_link(uow: UnitOfWork, *, link_id: int, now: datetime, links: Links) -> FamilyLink:
    link = _get_link(uow, links, link_id)
    updated = transition_link(link, LinkStatus.REJECTED, now=now)
    return links.update_status(
        uow, link_id, updated.status, updated.revoked_at, updated.rejected_at
    )


def _get_link(uow: UnitOfWork, links: Links, link_id: int) -> FamilyLink:
    link = links.get(uow, link_id)
    if link is None:
        raise NotFound("family link was not found")
    return link
