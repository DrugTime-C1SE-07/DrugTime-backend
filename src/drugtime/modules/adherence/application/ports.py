from datetime import datetime
from typing import Protocol
from uuid import UUID

from drugtime.modules.adherence.domain.alert import Alert
from drugtime.modules.adherence.domain.dose import (
    DoseConfirmation,
    DoseConfirmationPersistenceResult,
    DoseStatus,
)
from drugtime.shared.uow import UnitOfWork


class NotificationPort(Protocol):
    """CD8/QA.11: hiện thực ở drugtime.notification_gateway (FCM, mock; Zalo OA sau này)."""

    def send(self, alerts: list[Alert]) -> None: ...


class DoseLogs(Protocol):
    def upsert_confirmation(
        self, uow: UnitOfWork, c: DoseConfirmation, status: DoseStatus
    ) -> DoseConfirmationPersistenceResult: ...
    def mark_missed(self, uow: UnitOfWork, schedule_id: int, scheduled_at: datetime) -> int | None:
        """Tạo dòng Bỏ lỡ nếu chưa có; trả id dòng mới, None nếu đã tồn tại."""
        ...

    def erase_for_schedules(self, uow: UnitOfWork, schedule_ids: list[int]) -> None: ...


class Notifications(Protocol):
    def create_missed_alert(
        self, uow: UnitOfWork, recipient_id: UUID, patient_id: UUID, dedupe_key: str
    ) -> UUID | None:
        """ON CONFLICT (dedupe_key) DO NOTHING; None nếu đã có."""
        ...

    def erase_for_user(self, uow: UnitOfWork, user_id: UUID) -> None: ...


class ScanCursor(Protocol):
    def get(self, uow: UnitOfWork) -> datetime | None: ...
    def advance(self, uow: UnitOfWork, until: datetime) -> None: ...


class AccessGuard(Protocol):
    def authorize_adherence(
        self, uow: UnitOfWork, caller_id: UUID, caller_is_admin: bool, patient_id: UUID
    ) -> None: ...
    def caregivers_of(self, uow: UnitOfWork, patient_id: UUID) -> list[UUID]: ...


class Schedules(Protocol):
    def owner(self, uow: UnitOfWork, schedule_id: int) -> UUID | None: ...
    def ids_of(self, uow: UnitOfWork, user_id: UUID) -> list[int]: ...
    def occurrences_between(self, uow: UnitOfWork, start: datetime, end: datetime) -> list: ...


class DeviceTokens(Protocol):
    def android_tokens(self, uow: UnitOfWork, user_ids: list[UUID]) -> list[tuple[UUID, str]]: ...
