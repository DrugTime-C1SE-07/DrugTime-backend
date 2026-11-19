from typing import Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

Int64 = Annotated[int, Field(ge=1, le=9223372036854775807, json_schema_extra={"format": "int64"})]
ReminderStatus = Literal["accepted", "dispatched", "cancelled", "failed"]


class DoseReminderCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    client_uuid: UUID
    schedule_id: Int64
    scheduled_at: AwareDatetime


class DoseReminderReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: Int64
    patient_id: UUID
    schedule_id: Int64
    scheduled_at: AwareDatetime
    requested_at: AwareDatetime
    next_allowed_at: AwareDatetime
    status: ReminderStatus


class DoseReminderState(BaseModel):
    model_config = ConfigDict(extra="forbid")
    patient_id: UUID
    schedule_id: Int64
    scheduled_at: AwareDatetime
    last_reminder: DoseReminderReceipt | None


class ReceivedDoseReminder(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: Int64
    patient_id: UUID
    schedule_id: Int64
    scheduled_at: AwareDatetime
    requested_at: AwareDatetime
    is_read: bool
    status: ReminderStatus
    medication_name: str
    sender_name: Annotated[str, Field(min_length=1)] | None


class ReceivedDoseReminderPage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: list[ReceivedDoseReminder]
    total: Annotated[int, Field(ge=0)]
    unread_count: Annotated[int, Field(ge=0)]
