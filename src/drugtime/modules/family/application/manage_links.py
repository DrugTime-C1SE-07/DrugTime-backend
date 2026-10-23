import logging
from datetime import datetime
from uuid import UUID

from drugtime.modules.family.application.ports import Links
from drugtime.modules.family.domain.link import (
    FamilyLink,
    FamilyLinkError,
    LinkStatus,
    ensure_can_create_link,
    pending_link,
    transition_link,
)
from drugtime.shared.errors import Forbidden, NotFound
from drugtime.shared.uow import UnitOfWork

_log = logging.getLogger(__name__)


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


def revoke_link(
    uow: UnitOfWork,
    *,
    link_id: int,
    caller_id: UUID | None = None,
    now: datetime,
    links: Links,
) -> FamilyLink:
    link = links.get(uow, link_id)
    if link is None:
        raise Forbidden("khong_co_quyen")

    if caller_id is not None:
        if caller_id != link.patient_user_id and caller_id != link.family_user_id:
            raise Forbidden("khong_co_quyen")

    # Idempotent: nếu link đã revoked và sharing_enabled đã tắt thì giữ nguyên
    if link.status is LinkStatus.REVOKED and not link.sharing_enabled:
        return link

    # Domain validates the transition (catches e.g. rejected -> revoked)
    transition_link(link, LinkStatus.REVOKED, now=now)

    old_status = link.status.value
    old_sharing = link.sharing_enabled

    persisted = links.revoke(
        uow,
        link_id=link_id,
        caller_id=caller_id or link.patient_user_id,
        now=now,
    )
    if persisted is not None:
        _log.info("link_revoked link_id=%d caller=%s old_status=%s sharing %s->false",
                  link_id, caller_id, old_status, old_sharing)
        return persisted

    # SQL didn't match (race or status guard) -- re-read to determine error.
    # caller_id was verified above; re-check so strangers always get 403.
    current = links.get(uow, link_id)
    if current is not None and caller_id is not None:
        is_member = caller_id in (current.patient_user_id, current.family_user_id)
        if is_member and current.status is LinkStatus.REJECTED:
            raise FamilyLinkError(
                "invalid_link_transition",
                f"cannot transition family link from {current.status.value} to revoked",
            )
    raise Forbidden("khong_co_quyen")



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
