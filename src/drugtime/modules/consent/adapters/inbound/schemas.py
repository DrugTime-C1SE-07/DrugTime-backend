"""Request/response của /consents, khớp api_contract/openapi.json (task 1.14)."""

from datetime import datetime
from typing import Annotated, Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field

from drugtime.modules.consent.domain.consent import ConsentState
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
