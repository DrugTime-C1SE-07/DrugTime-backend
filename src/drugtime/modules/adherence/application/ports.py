from datetime import datetime
from typing import Protocol
from uuid import UUID

from drugtime.modules.adherence.domain.alert import Alert, NotificationRecord
from drugtime.modules.adherence.domain.dose import (
    DoseConfirmation,
    DoseConfirmationPersistenceResult,
    DoseStatus,
)
from drugtime.modules.adherence.domain.history import HistoryRange, HistoryRow
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


# Tách metadata trước PEP và nội dung sau PEP để application kiểm soát thứ tự truy cập.
class Notifications(Protocol):
    def metadata(
        self, uow: UnitOfWork, user_id: UUID, notification_id: int | None = None
    ) -> list[tuple[int, UUID]]: ...

    def authorized_records(
        self, uow: UnitOfWork, user_id: UUID, ids: list[int]
    ) -> list[NotificationRecord]: ...

    def create_missed_alert(
        self,
        uow: UnitOfWork,
        recipient_id: UUID,
        patient_id: UUID,
        dedupe_key: str,
        content: str | None = None,
        *,
        medication_name: str,
        scheduled_at: datetime,
    ) -> int | None:
        """ON CONFLICT (dedupe_key) DO NOTHING; None nếu đã có."""
        ...

    def mark_as_read(
        self,
        uow: UnitOfWork,
        notification_id: int,
        user_id: UUID,
        is_read: bool = True,
    ) -> NotificationRecord | None:
        """Cập nhật is_read, trả về None nếu không tìm thấy hoặc không thuộc user."""
        ...

    def erase_for_user(self, uow: UnitOfWork, user_id: UUID) -> None: ...


class PatientNames(Protocol):
    def get_patient_name(self, uow: UnitOfWork, patient_id: UUID) -> str | None: ...


class ScanCursor(Protocol):
    def get(self, uow: UnitOfWork) -> datetime | None: ...
    def advance(self, uow: UnitOfWork, until: datetime) -> None: ...


class AccessGuard(Protocol):
    def authorize_adherence(
        self, uow: UnitOfWork, caller_id: UUID, caller_is_admin: bool, patient_id: UUID
    ) -> None: ...
    def caregivers_of(self, uow: UnitOfWork, patient_id: UUID) -> list[UUID]: ...


class HistoryAccess(Protocol):
    def authorize_history(
        self, uow: UnitOfWork, caller_id: UUID, caller_is_admin: bool, patient_id: UUID
    ) -> None: ...


class AdherenceHistoryReader(Protocol):
    def read(
        self, uow: UnitOfWork, patient_id: UUID, period: HistoryRange, as_of: datetime
    ) -> list[HistoryRow]: ...


# Context lấy tên thuốc; thời điểm snapshot vẫn phải lấy từ occurrence đang quét.
class Schedules(Protocol):
    def alert_context(self, uow: UnitOfWork, schedule_id: int, patient_id: UUID) -> str | None: ...

    def owner(self, uow: UnitOfWork, schedule_id: int) -> UUID | None: ...
    def ids_of(self, uow: UnitOfWork, user_id: UUID) -> list[int]: ...
    def occurrences_between(self, uow: UnitOfWork, start: datetime, end: datetime) -> list: ...


class DeviceTokens(Protocol):
    def android_tokens(self, uow: UnitOfWork, user_ids: list[UUID]) -> list[tuple[UUID, str]]: ...
