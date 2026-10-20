import re
from datetime import date
from typing import Annotated, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StrictStr,
    field_validator,
    model_validator,
)

PositiveId = Annotated[
    int, Field(strict=True, ge=1, le=9223372036854775807, json_schema_extra={"format": "int64"})
]


def _reject_nul(value: str) -> str:
    if "\x00" in value:
        raise ValueError("Text must not contain NUL characters")
    return value


ConditionText = Annotated[StrictStr, AfterValidator(_reject_nul)]


def _health_profile_schema(schema: dict) -> None:
    schema["properties"]["email"] = {
        "type": ["string", "null"],
        "format": "email",
        "maxLength": 254,
        "description": "Current login email, null for accounts without an email identifier.",
    }


class ProfileUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    full_name: StrictStr = Field(min_length=1, pattern=r"\S")
    date_of_birth: date
    gender: Literal["nam", "nu", "khac", "male", "female", "other"]
    # Omission means leave the current login email unchanged; explicit null is invalid.
    email: StrictStr = Field(
        default=None,
        min_length=3,
        max_length=254,
        json_schema_extra={"format": "email"},
        description=(
            "Optional immediate login email change. Omit to preserve the current email; "
            "null is invalid."
        ),
    )

    @field_validator("gender", mode="before")
    @classmethod
    def normalize_gender(cls, value):
        return value.strip().lower() if isinstance(value, str) else value

    @field_validator("date_of_birth", mode="before")
    @classmethod
    def iso_date_only(cls, value):
        if not isinstance(value, str) or re.fullmatch(r"\d{4}-\d{2}-\d{2}", value) is None:
            raise ValueError("Expected an ISO calendar date")
        return value


class UserConditionCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    condition_id: PositiveId
    subtype: ConditionText | None = None
    stage: ConditionText | None = None


class UserConditionUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", json_schema_extra={"minProperties": 1})
    subtype: ConditionText | None = None
    stage: ConditionText | None = None

    @model_validator(mode="after")
    def nonempty(self):
        if not self.model_fields_set:
            raise ValueError("empty_condition_update")
        return self


class UserConditionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)
    id: PositiveId
    condition_id: PositiveId
    condition_name: str
    subtype: str | None
    stage: str | None


class HealthProfileResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        from_attributes=True,
        json_schema_extra=_health_profile_schema,
    )
    full_name: str | None
    date_of_birth: date | None
    gender: str | None
    email: str | None
    conditions: list[UserConditionResponse]


class ProfileError(BaseModel):
    detail: str


class ProfileValidationError(BaseModel):
    detail: str | list[dict]
