from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID

from drugtime.shared.errors import Conflict, DomainError, Forbidden

VIETNAM = timezone(timedelta(hours=7))
COOLDOWN = timedelta(seconds=600)
RETENTION = timedelta(days=30)


@dataclass(frozen=True)
class ReminderCommand:
    client_uuid: UUID
    schedule_id: int
    scheduled_at: datetime


@dataclass(frozen=True)
class ReminderRecord:
    id: int
    sender_user_id: UUID
    patient_id: UUID
    schedule_id: int
    scheduled_at: datetime
    requested_at: datetime
    next_allowed_at: datetime
    status: str
    notification_id: int
    is_read: bool = False

    def matches(self, patient_id: UUID, cmd: ReminderCommand) -> bool:
        return (self.patient_id, self.schedule_id, self.scheduled_at) == (
            patient_id,
            cmd.schedule_id,
            cmd.scheduled_at,
        )


@dataclass(frozen=True)
class ReminderPush:
    reminder_id: int
    device_token: str


@dataclass(frozen=True)
class ReminderTransportResult:
    accepted: bool
    unregistered: bool = False


def validate_occurrence(context, patient_id, scheduled_at, now, *, sending):
    if context is None:
        raise DomainError("invalid_dose_occurrence")
    if context.patient_id != patient_id:
        raise Forbidden("khong_co_quyen")
    if scheduled_at.tzinfo is None:
        raise DomainError("invalid_dose_occurrence")
    local = scheduled_at.astimezone(VIETNAM)
    if (
        scheduled_at >= now
        or scheduled_at < now - RETENTION
        or local.time().replace(tzinfo=None) != context.intake_time
        or local.isoweekday() not in context.days_of_week
        or scheduled_at < context.effective_from
        or (context.ended_at is not None and scheduled_at >= context.ended_at)
    ):
        raise DomainError("invalid_dose_occurrence")
    if sending and context.unavailable:
        raise Conflict("dose_unavailable")
