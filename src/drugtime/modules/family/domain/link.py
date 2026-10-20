from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from drugtime.shared.errors import Conflict, DomainError


class LinkStatus(StrEnum):
    PENDING = "pending"
    ACTIVE = "active"
    REVOKED = "revoked"
    REJECTED = "rejected"


class FamilyLinkError(DomainError):
    """Vi phạm quy tắc liên kết (422). `detail` trả cho client là mã ổn định `code`;
    `message` chỉ để đọc khi debug."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(code)
        self.code = code
        self.message = message


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
    client_uuid: UUID | None = None


def ensure_distinct_users(patient_user_id: UUID, family_user_id: UUID) -> None:
    if patient_user_id == family_user_id:
        raise FamilyLinkError(
            "self_link_not_allowed",
            "patient_user_id and family_user_id must be different",
        )


def ensure_can_create_link(
    patient_user_id: UUID, family_user_id: UUID, open_link: FamilyLink | None
) -> None:
    """Mỗi cặp (người bệnh, người thân) có tối đa một dòng pending/active (QD-34 (f)).

    `open_link` là dòng pending/active của cặp, nếu có. Dòng rejected/revoked không chặn:
    gửi lại tạo yêu cầu mới (QD-30, BS-04).
    """
    ensure_distinct_users(patient_user_id, family_user_id)
    if open_link is None:
        return
    if open_link.status is LinkStatus.PENDING:
        raise Conflict("link_request_pending")
    raise Conflict("already_linked")


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
            sharing_enabled=False,
            linked_at=link.linked_at,
            revoked_at=None,
            rejected_at=None,
            client_uuid=link.client_uuid,
        )
    if link.status is LinkStatus.PENDING and target is LinkStatus.REJECTED:
        return FamilyLink(
            id=link.id,
            patient_user_id=link.patient_user_id,
            family_user_id=link.family_user_id,
            status=LinkStatus.REJECTED,
            sharing_enabled=False,
            linked_at=link.linked_at,
            revoked_at=None,
            rejected_at=now,
            client_uuid=link.client_uuid,
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
            client_uuid=link.client_uuid,
        )
    raise FamilyLinkError(
        "invalid_link_transition",
        f"cannot transition family link from {link.status.value} to {target.value}",
    )
