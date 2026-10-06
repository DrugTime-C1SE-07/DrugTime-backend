"""Quy tắc ghi dose_logs (schema v11). Adapter SQL phải cài đúng các quy tắc này."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from uuid import UUID

from drugtime.shared.errors import DomainError

GRACE_PERIOD = timedelta(minutes=30)
LATE_CONFIRMATION_WINDOW = timedelta(minutes=120)


class DoseStatus(StrEnum):
    TAKEN = "da_uong"
    MISSED = "bo_lo"
    LATE = "uong_tre"


class DoseConfirmationError(DomainError):
    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail


@dataclass(frozen=True)
class DoseConfirmation:
    client_uuid: UUID
    schedule_id: int
    scheduled_at: datetime
    taken_at: datetime


@dataclass(frozen=True)
class DoseLogRecord:
    id: int
    client_uuid: UUID | None
    schedule_id: int
    scheduled_at: datetime
    taken_at: datetime | None
    status: DoseStatus
    synced_at: datetime | None


@dataclass(frozen=True)
class DoseConfirmationPersistenceResult:
    record: DoseLogRecord
    adherence_counted: bool


@dataclass(frozen=True)
class DoseConfirmationItemError:
    code: str
    http_status: int
    detail: str


@dataclass(frozen=True)
class DoseConfirmationResult:
    client_uuid: UUID
    schedule_id: int
    scheduled_at: datetime
    result: str
    dose_log_id: int | None = None
    dose_status: DoseStatus | None = None
    adherence_counted: bool | None = None
    synced_at: datetime | None = None
    error: DoseConfirmationItemError | None = None


@dataclass(frozen=True)
class DoseConfirmationBatchResult:
    items: list[DoseConfirmationResult]

    @property
    def total(self) -> int:
        return len(self.items)

    @property
    def synced(self) -> int:
        return sum(1 for item in self.items if item.result == "synced")

    @property
    def failed(self) -> int:
        return sum(1 for item in self.items if item.result == "failed")


class ClientUuidConflict(DomainError):
    def __init__(self) -> None:
        super().__init__("client_uuid is already used for a different dose confirmation")


def validate_confirmation(c: DoseConfirmation, now: datetime) -> None:
    if c.taken_at > now:
        raise DoseConfirmationError("taken_at_in_future", "taken_at must not be in the future")
    if c.taken_at < c.scheduled_at - GRACE_PERIOD:
        raise DoseConfirmationError(
            "taken_at_too_early",
            "taken_at must not be earlier than scheduled_at minus 30 minutes",
        )


def status_for_confirmation(c: DoseConfirmation, now: datetime) -> DoseStatus:
    validate_confirmation(c, now)
    if c.taken_at <= c.scheduled_at + GRACE_PERIOD:
        return DoseStatus.TAKEN
    if c.taken_at > c.scheduled_at + LATE_CONFIRMATION_WINDOW:
        return DoseStatus.MISSED
    return DoseStatus.LATE


def adherence_counted_for_status(status: DoseStatus) -> bool:
    return status is not DoseStatus.MISSED


def status_after_confirmation(existing: DoseStatus | None) -> DoseStatus:
    """Chưa có dòng → Đã uống; Bỏ lỡ → Uống trễ; đã xác nhận → giữ nguyên (idempotent)."""
    if existing is None:
        return DoseStatus.TAKEN
    if existing is DoseStatus.MISSED:
        return DoseStatus.LATE
    return existing


def may_mark_missed(existing: DoseStatus | None) -> bool:
    """Worker chỉ tạo Bỏ lỡ khi chưa có dòng; không bao giờ ghi đè liều đã xác nhận."""
    return existing is None
