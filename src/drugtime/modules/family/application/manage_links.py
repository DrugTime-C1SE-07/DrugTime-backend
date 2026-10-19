from datetime import datetime
from uuid import UUID

from drugtime.modules.family.application.ports import (
    Confirmations,
    LinkAudit,
    Links,
    SharingConsent,
)
from drugtime.modules.family.domain.consent_confirmation import LinkApproval
from drugtime.modules.family.domain.link import (
    FamilyLink,
    LinkStatus,
    ensure_can_create_link,
    pending_link,
    transition_link,
)
from drugtime.shared.errors import Conflict, DomainError, Forbidden, NotFound
from drugtime.shared.uow import UnitOfWork


def create_link_request(
    uow: UnitOfWork, *, patient_id: UUID, family_id: UUID, links: Links
) -> FamilyLink:
    open_link = links.find_open_by_pair(uow, patient_id, family_id)
    ensure_can_create_link(patient_id, family_id, open_link)
    return links.create(uow, pending_link(patient_id, family_id))


def deny(
    audit: LinkAudit,
    actor_id: UUID,
    operation: str,
    *,
    patient_id: UUID | None = None,
    link_id: int | None = None,
    reason: str = "khong_co_quyen",
) -> None:
    audit.denied(actor_id, patient_id, link_id, operation, reason)
    raise Forbidden(reason)


def owned_link(
    uow: UnitOfWork,
    *,
    link_id: int,
    actor_id: UUID,
    is_admin: bool,
    operation: str,
    links: Links,
    audit: LinkAudit,
) -> FamilyLink:
    if is_admin:
        deny(audit, actor_id, operation)
    link = links.get_for_update(uow, link_id)
    if link is None:
        raise NotFound("family_link_not_found")
    if actor_id != link.patient_user_id:
        deny(audit, actor_id, operation, patient_id=link.patient_user_id, link_id=link.id)
    return link


def approve_link(
    uow: UnitOfWork,
    *,
    link_id: int,
    actor_id: UUID,
    is_admin: bool,
    family_user_id: UUID,
    consent_confirmed: bool,
    document_version: str,
    links: Links,
    confirmations: Confirmations,
    consent: SharingConsent,
    audit: LinkAudit,
) -> LinkApproval:
    link = owned_link(
        uow,
        link_id=link_id,
        actor_id=actor_id,
        is_admin=is_admin,
        operation="approve",
        links=links,
        audit=audit,
    )
    if family_user_id != link.family_user_id:
        deny(audit, actor_id, "approve", patient_id=link.patient_user_id, link_id=link.id)
    if link.status not in (LinkStatus.PENDING, LinkStatus.ACTIVE):
        raise Conflict("invalid_link_transition")
    if not consent.lock_active(uow, link.patient_user_id):
        deny(
            audit,
            actor_id,
            "approve",
            patient_id=link.patient_user_id,
            link_id=link.id,
            reason="consent_revoked",
        )
    if consent_confirmed is not True:
        raise DomainError("consent_confirmation_required")
    if link.status is LinkStatus.ACTIVE:
        confirmation = confirmations.get(uow, link)
        if confirmation is None:
            raise Conflict("consent_confirmation_missing")
        if confirmation.document_version != document_version:
            raise Conflict("link_approval_conflict")
    else:
        consent.check_version(document_version)
        confirmation = confirmations.insert(uow, link, document_version)
        updated = transition_link(link, LinkStatus.ACTIVE, now=confirmation.confirmed_at)
        link = links.update_status(
            uow, link_id, updated.status, updated.revoked_at, updated.rejected_at
        )
    audit.allowed(uow, actor_id, link.patient_user_id, link.id, "approve")
    return LinkApproval(link, confirmation)


def reject_link(
    uow: UnitOfWork,
    *,
    link_id: int,
    actor_id: UUID,
    is_admin: bool,
    links: Links,
    confirmations: Confirmations,
    audit: LinkAudit,
) -> FamilyLink:
    link = owned_link(
        uow,
        link_id=link_id,
        actor_id=actor_id,
        is_admin=is_admin,
        operation="reject",
        links=links,
        audit=audit,
    )
    if link.status is LinkStatus.PENDING:
        updated = transition_link(link, LinkStatus.REJECTED, now=confirmations.now(uow))
        link = links.update_status(
            uow, link_id, updated.status, updated.revoked_at, updated.rejected_at
        )
    elif link.status is not LinkStatus.REJECTED:
        raise Conflict("invalid_link_transition")
    audit.allowed(uow, actor_id, link.patient_user_id, link.id, "reject")
    return link


def revoke_link(uow: UnitOfWork, *, link_id: int, now: datetime, links: Links) -> FamilyLink:
    # Existing revoke behavior; caller enforcement for that endpoint is a separate task.
    link = _get_link(uow, links, link_id)
    updated = transition_link(link, LinkStatus.REVOKED, now=now)
    return links.update_status(
        uow, link_id, updated.status, updated.revoked_at, updated.rejected_at
    )


def _get_link(uow: UnitOfWork, links: Links, link_id: int) -> FamilyLink:
    link = links.get(uow, link_id)
    if link is None:
        raise NotFound("family_link_not_found")
    return link
