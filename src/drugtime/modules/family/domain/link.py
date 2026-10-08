from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from drugtime.shared.errors import DomainError


class LinkStatus(StrEnum):
    PENDING = "pending"
    ACTIVE = "active"
    REVOKED = "revoked"
    REJECTED = "rejected"


class FamilyLinkError(DomainError):
    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail


@dataclass(frozen=True)
class FamilyLink:
    id: int | None
    patient_user_id: UUID
    family_user_id: UUID
    status: LinkStatus
    sharing_enabled: bool = False
    linked_at: datetime | None = None
    revoked_at: datetime | None = None
    rejected_at: datetime | None = None


def ensure_distinct_users(patient_user_id: UUID, family_user_id: UUID) -> None:
    if patient_user_id == family_user_id:
        raise FamilyLinkError(
            "self_link_not_allowed",
            "patient_user_id and family_user_id must be different",
        )


def ensure_can_create_link(
    patient_user_id: UUID, family_user_id: UUID, existing: FamilyLink | None
) -> None:
    ensure_distinct_users(patient_user_id, family_user_id)
    if existing is not None:
        raise FamilyLinkError(
            "link_already_exists",
            "patient-family link already exists for this role pair",
        )


def pending_link(patient_user_id: UUID, family_user_id: UUID) -> FamilyLink:
    ensure_distinct_users(patient_user_id, family_user_id)
    return FamilyLink(
        id=None,
        patient_user_id=patient_user_id,
        family_user_id=family_user_id,
        status=LinkStatus.PENDING,
    )


def transition_link(link: FamilyLink, target: LinkStatus, *, now: datetime) -> FamilyLink:
    if link.status is LinkStatus.PENDING and target is LinkStatus.ACTIVE:
        return FamilyLink(
            id=link.id,
            patient_user_id=link.patient_user_id,
            family_user_id=link.family_user_id,
            status=LinkStatus.ACTIVE,
            sharing_enabled=link.sharing_enabled,
            linked_at=link.linked_at,
            revoked_at=None,
            rejected_at=None,
        )
    if link.status is LinkStatus.PENDING and target is LinkStatus.REJECTED:
        return FamilyLink(
            id=link.id,
            patient_user_id=link.patient_user_id,
            family_user_id=link.family_user_id,
            status=LinkStatus.REJECTED,
            sharing_enabled=link.sharing_enabled,
            linked_at=link.linked_at,
            revoked_at=None,
            rejected_at=now,
        )
    if link.status is LinkStatus.ACTIVE and target is LinkStatus.REVOKED:
        return FamilyLink(
            id=link.id,
            patient_user_id=link.patient_user_id,
            family_user_id=link.family_user_id,
            status=LinkStatus.REVOKED,
            sharing_enabled=link.sharing_enabled,
            linked_at=link.linked_at,
            revoked_at=now,
            rejected_at=None,
        )
    raise FamilyLinkError(
        "invalid_link_transition",
        f"cannot transition family link from {link.status.value} to {target.value}",
    )
