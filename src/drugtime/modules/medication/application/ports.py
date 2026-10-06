from datetime import datetime, time
from typing import Protocol
from uuid import UUID

from drugtime.modules.medication.domain.user_medication import (
    MedicationInfo,
    MedicationState,
    NewMedication,
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
        """SELECT ... FOR UPDATE dòng thuốc, rồi đọc trạng thái và giờ DB **sau khi** có khóa.

        Mốc này dùng cho mọi ended_at/effective_from của thao tác sửa. Không dùng now(): now()
        là lúc transaction bắt đầu, có thể sớm hơn effective_from mà request khác vừa ghi
        trong lúc mình chờ khóa (lỗi B1)."""
        ...

    def update_fields(self, uow: UnitOfWork, user_medication_id: int, fields: dict) -> None: ...
    def close_open_schedules(
        self, uow: UnitOfWork, user_medication_id: int, at: datetime
    ) -> None: ...
    def stop(self, uow: UnitOfWork, user_medication_id: int, at: datetime) -> None: ...
    def mark_deleted(self, uow: UnitOfWork, user_medication_id: int, at: datetime) -> None:
        """Đặt deleted_at; gọi sau close_open_schedules và stop (CHECK cần ended_at)."""
        ...

    def reactivate(self, uow: UnitOfWork, user_medication_id: int, at: datetime) -> int:
        """Dùng lại thuốc đã ngừng: chép từng lịch đóng cùng lúc với lần ngừng gần nhất
        (ended_at của lịch = ended_at của thuốc) thành lịch mới effective_from = at, **rồi**
        mới bỏ ended_at của thuốc. Trả số lịch đã mở lại."""
        ...

    def read(self, uow: UnitOfWork, user_medication_id: int) -> UserMedicationRecord: ...
