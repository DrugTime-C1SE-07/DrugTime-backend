"""Response của /family, khớp api_contract/openapi.json (task 3.10)."""

from typing import Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StrictBool, field_validator

from drugtime.modules.family.domain.link_code import LinkCode as LinkCodeRecord

_CODE = "[A-HJKMNP-Z2-9]{10}"


class LinkCode(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: Annotated[str, Field(pattern=f"^{_CODE}$", min_length=10, max_length=10)]
    qr_payload: Annotated[str, Field(pattern=rf"^drugtime://link\?code={_CODE}$")]

    @classmethod
    def from_record(cls, record: LinkCodeRecord) -> "LinkCode":
        return cls(code=record.code, qr_payload=record.qr_payload)


class ErrorDetail(BaseModel):
    detail: str


PositiveId = Annotated[
    int, Field(ge=1, le=9223372036854775807, json_schema_extra={"format": "int64"})
]
DocumentVersion = Annotated[str, Field(strict=True, min_length=1, max_length=64)]


class PendingFamilyLink(BaseModel):
    model_config = ConfigDict(extra="forbid")

    link_id: PositiveId
    family_user_id: UUID
    family_full_name: Annotated[str, Field(min_length=1)] | None
    status: Literal["pending"]
    requested_at: AwareDatetime


class PendingFamilyLinkList(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[PendingFamilyLink]


class FamilyLinkApprovalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    family_user_id: UUID
    consent_confirmed: Annotated[StrictBool, Field(json_schema_extra={"enum": [True]})]
    document_version: DocumentVersion

    @field_validator("consent_confirmed")
    @classmethod
    def require_confirmation(cls, value: bool) -> bool:
        if value is not True:
            raise ValueError("explicit consent confirmation is required")
        return value


class FamilyLinkConsentConfirmation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: PositiveId
    purpose: Literal["family_sharing"]
    document_version: DocumentVersion
    confirmed_at: AwareDatetime


class FamilyLinkApproval(BaseModel):
    model_config = ConfigDict(extra="forbid")

    link_id: PositiveId
    family_user_id: UUID
    status: Literal["active"]
    sharing_enabled: bool
    consent_confirmation: FamilyLinkConsentConfirmation


class FamilyLinkRejection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    link_id: PositiveId
    family_user_id: UUID
    status: Literal["rejected"]
    rejected_at: AwareDatetime
