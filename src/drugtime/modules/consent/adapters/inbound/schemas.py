"""Request/response của module consent, khớp api_contract/openapi.json."""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field

from drugtime.modules.consent.domain.consent import ConsentState
from drugtime.modules.consent.domain.deletion_request import PendingDeletionRequest
from drugtime.modules.consent.domain.purpose import Purpose
from drugtime.shared.config import get_settings


class ConsentGrantRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    purpose: Purpose
    document_version: Annotated[str, Field(min_length=1, max_length=64)]


class Consent(BaseModel):
    purpose: Purpose
    status: Literal["granted", "not_granted"]
    granted_at: datetime | None
    document_version: str | None
    current_document_version: str

    @classmethod
    def from_state(cls, state: ConsentState) -> "Consent":
        active = state.active
        return cls(
            purpose=state.purpose,
            status="not_granted" if active is None else "granted",
            granted_at=None
            if active is None
            else active.granted_at.astimezone(ZoneInfo(get_settings().timezone)),
            document_version=None if active is None else active.document_version,
            current_document_version=state.current_document_version,
        )


class ConsentList(BaseModel):
    items: list[Consent]


class PendingDeletionQueueQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    skip: Annotated[int, Field(ge=0)] = 0
    limit: Annotated[int, Field(ge=1, le=100)] = 20


class PendingDataDeletionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: Annotated[int, Field(ge=1, json_schema_extra={"format": "int64"})]
    user_id: UUID
    requested_at: datetime
    status: Literal["cho_duyet"]

    @classmethod
    def from_record(cls, record: PendingDeletionRequest) -> "PendingDataDeletionRequest":
        return cls(
            id=record.id,
            user_id=record.user_id,
            requested_at=record.requested_at.astimezone(ZoneInfo(get_settings().timezone)),
            status="cho_duyet",
        )


class PendingDataDeletionRequestPage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: Annotated[list[PendingDataDeletionRequest], Field(max_length=100)]
    total: Annotated[int, Field(ge=0)]
