import re
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import (
    AliasChoices,
    AwareDatetime,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    RootModel,
    field_validator,
    model_validator,
)

from drugtime.modules.adherence.domain.history import VIETNAM


def _int64_schema(schema: dict) -> None:
    # FastAPI's OpenAPI model stores numeric bounds as floats. 2**63 is exactly
    # representable; an exclusive bound preserves PostgreSQL bigint's maximum.
    schema.pop("maximum", None)
    schema.update(format="int64", exclusiveMaximum=9223372036854775808)


PositiveId = Annotated[int, Field(ge=1, le=9223372036854775807, json_schema_extra=_int64_schema)]
Count = Annotated[int, Field(ge=0)]
Rate = Annotated[float, Field(ge=0, le=100, multiple_of=0.01)]


def _iso_date(value):
    if value is not None and (
        not isinstance(value, str) or re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value) is None
    ):
        raise ValueError("Expected YYYY-MM-DD")
    return value


QueryDate = Annotated[date | None, BeforeValidator(_iso_date)]


def _dose_constraints(schema: dict) -> None:
    schema["allOf"] = [
        {
            "if": {"properties": {"status": {"enum": ["da_uong", "uong_tre"]}}},
            "then": {
                "properties": {
                    "taken_at": {"type": "string", "format": "date-time"},
                    "status_source": {"const": "recorded"},
                }
            },
        },
        {
            "if": {"properties": {"status": {"enum": ["bo_lo", "cho_xac_nhan", "chua_xac_minh"]}}},
            "then": {"properties": {"taken_at": {"type": "null"}}},
        },
        {
            "if": {"properties": {"status": {"enum": ["cho_xac_nhan", "chua_xac_minh"]}}},
            "then": {"properties": {"status_source": {"const": "inferred"}}},
        },
    ]


class AdherenceDose(BaseModel):
    model_config = ConfigDict(
        extra="forbid", from_attributes=True, json_schema_extra=_dose_constraints
    )
    medication_id: PositiveId
    medication_name: str
    schedule_id: PositiveId
    scheduled_at: AwareDatetime
    taken_at: AwareDatetime | None
    status: Literal["da_uong", "uong_tre", "bo_lo", "cho_xac_nhan", "chua_xac_minh"]
    status_source: Literal["recorded", "inferred"]

    @field_validator("scheduled_at", "taken_at")
    @classmethod
    def vietnam_timestamp(cls, value):
        return value.astimezone(VIETNAM) if value is not None else None

    @model_validator(mode="after")
    def valid_confirmation(self):
        confirmed = self.status in ("da_uong", "uong_tre")
        if confirmed != (self.taken_at is not None):
            raise ValueError("invalid_adherence_confirmation_timestamp")
        if confirmed and self.status_source != "recorded":
            raise ValueError("confirmation_must_be_recorded")
        if self.status in ("cho_xac_nhan", "chua_xac_minh") and self.status_source != "inferred":
            raise ValueError("pending_must_be_inferred")
        return self


class AdherenceSummary(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        from_attributes=True,
        json_schema_extra={
            "allOf": [
                {
                    "if": {"properties": {"counted": {"const": 0}}},
                    "then": {"properties": {"adherence_rate": {"type": "null"}}},
                    "else": {"properties": {"adherence_rate": {"type": "number"}}},
                },
            ]
        },
    )
    total: Count
    taken: Count
    late: Count
    missed: Count
    pending: Count
    unverified: Count
    counted: Count
    adherence_rate: Rate | None

    @model_validator(mode="after")
    def valid_counts_and_rate(self):
        if self.counted != self.taken + self.late + self.missed:
            raise ValueError("invalid_adherence_counted")
        if self.total != self.counted + self.pending + self.unverified:
            raise ValueError("invalid_adherence_total")
        expected = (
            (Decimal(100) * (self.taken + self.late) / self.counted).quantize(
                Decimal("0.01"), ROUND_HALF_UP
            )
            if self.counted
            else None
        )
        actual = Decimal(str(self.adherence_rate)) if self.adherence_rate is not None else None
        if actual != expected:
            raise ValueError("invalid_adherence_rate")
        return self


class AdherenceDateGroup(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)
    date: date
    summary: AdherenceSummary
    doses: list[AdherenceDose] = Field(min_length=1)


class AdherenceMedicationGroup(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)
    medication_id: PositiveId
    medication_name: str
    summary: AdherenceSummary
    doses: list[AdherenceDose] = Field(min_length=1)


class _HistoryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)
    patient_id: UUID
    start: date = Field(validation_alias=AliasChoices("from", "start"), serialization_alias="from")
    end: date = Field(validation_alias=AliasChoices("to", "end"), serialization_alias="to")
    timezone: Literal["Asia/Ho_Chi_Minh"]
    as_of: AwareDatetime
    # Bắt buộc, có thể null (chưa từng đồng bộ); chỉ trả cho người đã qua PEP (3.19).
    patient_last_synced_at: AwareDatetime | None
    summary: AdherenceSummary

    @field_validator("as_of", "patient_last_synced_at")
    @classmethod
    def vietnam_timestamp(cls, value):
        return value.astimezone(VIETNAM) if value is not None else None


class AdherenceByDateResponse(_HistoryResponse):
    group_by: Literal["date"]
    groups: list[AdherenceDateGroup]


class AdherenceByMedicationResponse(_HistoryResponse):
    group_by: Literal["medication"]
    groups: list[AdherenceMedicationGroup]


class AdherenceHistoryResponse(
    RootModel[
        Annotated[
            AdherenceByDateResponse | AdherenceByMedicationResponse, Field(discriminator="group_by")
        ]
    ]
):
    pass


class AdherenceError(BaseModel):
    model_config = ConfigDict(extra="allow")
    detail: str


class _ValidationIssue(BaseModel):
    loc: list[str | int]
    msg: str
    type: str
    input: Any = None
    ctx: dict[str, Any] = Field(default_factory=dict)


class AdherenceRequestValidationError(BaseModel):
    detail: list[_ValidationIssue]
