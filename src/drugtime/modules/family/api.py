"""Giao diện công khai của family."""

from uuid import UUID

from drugtime.modules.family.adapters.inbound.http import router
from drugtime.modules.family.adapters.outbound.module_gateways import SharingConsentGateway
from drugtime.modules.family.adapters.outbound.sql_confirmations import SqlConfirmations
from drugtime.modules.family.adapters.outbound.sql_link_audit import SqlLinkAudit
from drugtime.modules.family.adapters.outbound.sql_links import SqlLinks
from drugtime.modules.family.application import manage_links
from drugtime.modules.family.domain.consent_confirmation import LinkApproval
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


def approve_link(
    uow: UnitOfWork,
    *,
    link_id: int,
    actor_id: UUID,
    is_admin: bool,
    family_user_id: UUID,
    consent_confirmed: bool,
    document_version: str,
) -> LinkApproval:
    return manage_links.approve_link(
        uow,
        link_id=link_id,
        actor_id=actor_id,
        is_admin=is_admin,
        family_user_id=family_user_id,
        consent_confirmed=consent_confirmed,
        document_version=document_version,
        links=SqlLinks(),
        confirmations=SqlConfirmations(),
        consent=SharingConsentGateway(),
        audit=SqlLinkAudit(),
    )


def revoke_link(
    uow: UnitOfWork,
    *,
    link_id: int,
    actor_id: UUID,
    is_admin: bool,
) -> FamilyLink:
    return manage_links.revoke_link(
        uow,
        link_id=link_id,
        actor_id=actor_id,
        is_admin=is_admin,
        links=SqlLinks(),
        confirmations=SqlConfirmations(),
        audit=SqlLinkAudit(),
    )


def reject_link(
    uow: UnitOfWork,
    *,
    link_id: int,
    actor_id: UUID,
    is_admin: bool,
) -> FamilyLink:
    return manage_links.reject_link(
        uow,
        link_id=link_id,
        actor_id=actor_id,
        is_admin=is_admin,
        links=SqlLinks(),
        confirmations=SqlConfirmations(),
        audit=SqlLinkAudit(),
    )


def has_active_sharing_link(uow: UnitOfWork, patient_id: UUID, family_id: UUID) -> bool:
    return SqlLinks().has_active_sharing_link(uow, patient_id, family_id)


def sharing_family_ids(uow: UnitOfWork, patient_id: UUID) -> list[UUID]:
    return SqlLinks().sharing_family_ids(uow, patient_id)


class _Eraser:
    name = "family"

    def erase_user(self, uow: UnitOfWork, user_id: UUID) -> None:
        SqlLinks().erase(uow, user_id)


eraser = _Eraser()
