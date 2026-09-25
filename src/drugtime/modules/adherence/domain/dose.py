"""Quy tắc ghi dose_logs (schema v9). Adapter SQL phải cài đúng các quy tắc này."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from drugtime.shared.errors import DomainError


class DoseStatus(StrEnum):
    TAKEN = "Đã uống"
    MISSED = "Bỏ lỡ"
    LATE = "Uống trễ"


@dataclass(frozen=True)
class DoseConfirmation:
    client_uuid: UUID
    schedule_id: UUID
    scheduled_at: datetime
    taken_at: datetime


def validate_confirmation(c: DoseConfirmation, now: datetime) -> None:
    if c.taken_at > now:
        raise DomainError("taken_at không được ở tương lai")


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
