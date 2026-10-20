from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from drugtime.modules.family.domain.link import FamilyLink


@dataclass(frozen=True)
class ConsentConfirmation:
    id: int
    link_id: int
    patient_user_id: UUID
    family_user_id: UUID
    purpose: str
    document_version: str
    confirmed_at: datetime


@dataclass(frozen=True)
class LinkApproval:
    link: FamilyLink
    confirmation: ConsentConfirmation


@dataclass(frozen=True)
class PendingLink:
    link_id: int
    family_user_id: UUID
    family_full_name: str | None
    requested_at: datetime
