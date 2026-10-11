from collections.abc import Sequence
from datetime import datetime, time
from typing import Protocol
from uuid import UUID

from drugtime.modules.medication.domain.schedule_changes import ClosedSchedule, NewSchedule
from drugtime.modules.medication.domain.user_medication import (
    MedicationInfo,
    MedicationState,
    NewMedication,
    PatientScheduleRecord,
    UserMedicationRecord,
)
from drugtime.shared.uow import UnitOfWork


class AccessGuard(Protocol):
    """PEP của access, scope danh_sach_thuoc. Raise Forbidden nếu không có quyền."""

    def authorize_read(
        self, uow: UnitOfWork, caller_id: UUID, caller_is_admin: bool, patient_id: UUID
    ) -> None: ...
    def authorize_write(
        self, uow: UnitOfWork, caller_id: UUID, caller_is_admin: bool, patient_id: UUID
    ) -> None: ...


class RecordedDoses(Protocol):
    """Liều đã ghi (dose_logs, thuộc adherence), nối qua composition root."""

    def latest_at_or_after(
        self, uow: UnitOfWork, schedule_ids: list[int], at: datetime
    ) -> dict[int, datetime]:
        """Giờ dự kiến muộn nhất của liều có giờ dự kiến >= at, theo id lịch."""
        ...


class Catalog(Protocol):
    def get_medication(
        self, uow: UnitOfWork, medication_id: int, *, include_deleted: bool = False
    ) -> MedicationInfo | None: ...


class UserMedications(Protocol):
    def owner_of(self, uow: UnitOfWork, user_medication_id: int) -> UUID | None:
        """Chủ thuốc; None nếu không có hoặc đã xoá mềm (mọi endpoint coi như không tồn tại)."""
        ...

    def find_by_client_uuid(
        self, uow: UnitOfWork, user_id: UUID, client_uuid: UUID
    ) -> tuple[int, bool] | None:
        """(id, đã xoá mềm) của thuốc tạo bằng client_uuid này; None nếu chưa dùng."""
        ...

    def ids_of(self, uow: UnitOfWork, user_id: UUID) -> list[int]:
        """Id thuốc chưa xoá của người dùng, id giảm dần."""
        ...

    def default_prescription(self, uow: UnitOfWork, user_id: UUID) -> int:
        """Id đơn thuốc mặc định của người dùng; tạo nếu chưa có (an toàn khi chạy song song)."""
        ...

    def insert(
        self,
        uow: UnitOfWork,
        user_id: UUID,
        prescription_id: int,
        cmd: NewMedication,
        has_interaction_data: bool,
    ) -> int | None:
        """ON CONFLICT (user_id, client_uuid) DO NOTHING; None nếu client_uuid đã dùng."""
        ...

    def insert_schedules(
        self,
        uow: UnitOfWork,
        user_medication_id: int,
        intake_times: tuple[time, ...],
        days_of_week: tuple[int, ...],
        effective_from: datetime | None = None,
    ) -> None:
        """effective_from None = now() của transaction (thuốc mới, không ai khác sửa được)."""
        ...

    def lock(self, uow: UnitOfWork, user_medication_id: int) -> tuple[MedicationState, datetime]:
        """SELECT ... FOR UPDATE dòng thuốc, rồi đọc trạng thái, lịch đang mở, lịch đóng có
        ended_at sau mốc khóa, và giờ DB **sau khi** có khóa.

        Mốc này dùng cho mọi ended_at/effective_from của thao tác sửa. Không dùng now(): now()
        là lúc transaction bắt đầu, có thể sớm hơn effective_from mà request khác vừa ghi
        trong lúc mình chờ khóa (lỗi B1)."""
        ...

    def update_fields(self, uow: UnitOfWork, user_medication_id: int, fields: dict) -> None: ...
    def closed_by_stop(
        self, uow: UnitOfWork, user_medication_id: int, stopped_at: datetime
    ) -> tuple[ClosedSchedule, ...]:
        """Lịch mang dấu đóng bởi lần ngừng tại stopped_at, id tăng dần."""
        ...

    def resume(self, uow: UnitOfWork, user_medication_id: int) -> None:
        """Bỏ ended_at của thuốc (dùng lại); lịch mở lại do add_schedules ghi."""
        ...

    def close_schedule(
        self,
        uow: UnitOfWork,
        schedule_id: int,
        ended_at: datetime,
        stopped_at: datetime | None = None,
    ) -> None:
        """Đóng một lịch đang mở tại ended_at do domain tính. Ngừng hoặc xoá thuốc truyền
        stopped_at (ended_at của thuốc) để đánh dấu lịch cần mở lại khi dùng lại."""
        ...

    def add_schedules(
        self, uow: UnitOfWork, user_medication_id: int, schedules: Sequence[NewSchedule]
    ) -> None:
        """Thêm lịch với effective_from và reminder_enabled do domain tính."""
        ...

    def patient_schedules(
        self, uow: UnitOfWork, patient_id: UUID, after_id: int, limit: int
    ) -> list[PatientScheduleRecord]:
        """Lịch đang mở hoặc đóng trong 30 ngày của thuốc chưa xoá, id > after_id, id tăng dần."""
        ...

    def stop(self, uow: UnitOfWork, user_medication_id: int, at: datetime) -> None: ...
    def mark_deleted(self, uow: UnitOfWork, user_medication_id: int, at: datetime) -> None:
        """Đặt deleted_at; gọi sau khi đóng lịch và stop (CHECK cần ended_at)."""
        ...

    def read(self, uow: UnitOfWork, user_medication_id: int) -> UserMedicationRecord: ...
