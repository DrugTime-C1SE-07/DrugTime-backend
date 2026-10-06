"""Thuốc của người bệnh: kiểu và quy tắc thêm/sửa (task 2.01). Hàm thuần, không I/O."""

from dataclasses import dataclass, field, replace
from datetime import datetime, time
from decimal import Decimal
from enum import StrEnum
from typing import Any
from uuid import UUID

from drugtime.shared.errors import DomainError

ALL_WEEK: tuple[int, ...] = (1, 2, 3, 4, 5, 6, 7)

RULE_VIOLATION = "medication_rule_violation"
STOPPED = "medication_stopped"
NOT_FOUND = "user_medication_not_found"
CATALOG_NOT_FOUND = "catalog_medication_not_found"


# Thuốc được uống theo cách nào , theo lịch hay uống khi cần
class DosingMode(StrEnum):
    SCHEDULED = "scheduled"
    AS_NEEDED = "as_needed"


# Cách uống
class IntakeTiming(StrEnum):
    BEFORE_MEAL = "before_meal"
    AFTER_MEAL = "after_meal"
    ANY_TIME = "any_time"


# Loại thuốc mới được thêm vào
@dataclass(frozen=True)
class NewMedication:
    client_uuid: UUID
    medication_id: int
    quantity_per_dose: Decimal
    dosing_mode: DosingMode
    intake_times: tuple[time, ...] | None = None
    days_of_week: tuple[int, ...] | None = None
    max_doses_per_day: int | None = None
    intake_timing: IntakeTiming | None = None
    stock_quantity: int | None = None

    # Xây dựng thuốc tính tính toán liểu lượng trên ngày
    @property
    def doses_per_day(self) -> int:
        if self.dosing_mode is DosingMode.SCHEDULED:
            return len(self.intake_times or ())
        return self.max_doses_per_day or 0


# Thay đổi thông tin thuốc
@dataclass(frozen=True)
class MedicationChanges:
    """Body của PATCH. `sent` phân biệt field không gửi với field gửi `null`."""

    sent: frozenset[str]
    quantity_per_dose: Decimal | None = None
    dosing_mode: DosingMode | None = None
    intake_times: tuple[time, ...] | None = None
    max_doses_per_day: int | None = None
    intake_timing: IntakeTiming | None = None
    stock_quantity: int | None = None
    stopped: bool = False


# Trạng thái thuốc
@dataclass(frozen=True)
class MedicationState:
    """Trạng thái hiện tại của thuốc, đọc dưới khóa dòng."""

    dosing_mode: DosingMode
    stopped: bool
    open_days_of_week: tuple[int, ...] | None  # của lịch đang mở; None nếu không có lịch mở
    deleted: bool = False  # đã xoá mềm; đọc dưới khóa để thấy lần xoá vừa commit


@dataclass(frozen=True)
class UpdatePlan:
    fields: dict[str, Any] = field(default_factory=dict)  # cột của user_medications cần cập nhật
    close_open_schedules: bool = False
    new_intake_times: tuple[time, ...] = ()
    new_days_of_week: tuple[int, ...] = ALL_WEEK
    stop: bool = False
    reactivate: bool = False  # dùng lại thuốc đã ngừng: mở lại lịch của lần ngừng gần nhất

    @property
    def is_noop(self) -> bool:
        return not (
            self.fields
            or self.close_open_schedules
            or self.new_intake_times
            or self.stop
            or self.reactivate
        )


@dataclass(frozen=True)
class MedicationInfo:
    """Thông tin danh mục dùng để hiển thị thuốc của người bệnh."""

    id: int
    name: str
    strength_text: str | None
    dosage_form: str | None
    has_active_ingredients: bool
    active_ingredient: str | None = None  # văn bản thô của danh mục, chỉ để hiển thị


@dataclass(frozen=True)
class ScheduleView:
    id: int
    intake_time: time
    days_of_week: tuple[int, ...]
    reminder_enabled: bool
    effective_from: datetime


@dataclass(frozen=True)
class UserMedicationRecord:
    id: int
    user_id: UUID
    medication_id: int
    dosing_mode: DosingMode
    quantity_per_dose: Decimal
    doses_per_day: int
    intake_timing: IntakeTiming | None
    stock_quantity: int | None
    has_interaction_data: bool
    ended_at: datetime | None
    schedules: tuple[ScheduleView, ...]  # lịch đang mở, sắp theo intake_time


@dataclass(frozen=True)
class UserMedicationView:
    record: UserMedicationRecord
    medication: MedicationInfo


def _violation() -> DomainError:
    return DomainError(RULE_VIOLATION)


def validate_new(cmd: NewMedication) -> NewMedication:
    """Kiểm quan hệ giữa các field; trả bản đã chuẩn hóa (giờ tăng dần, ngày mặc định cả tuần)."""
    if cmd.dosing_mode is DosingMode.SCHEDULED:
        if not cmd.intake_times or cmd.max_doses_per_day is not None:
            raise _violation()
        return replace(
            cmd,
            intake_times=tuple(sorted(cmd.intake_times)),
            days_of_week=tuple(sorted(cmd.days_of_week or ALL_WEEK)),
        )
    if (
        cmd.max_doses_per_day is None
        or cmd.intake_times is not None
        or cmd.days_of_week is not None
    ):
        raise _violation()
    return cmd


def plan_update(state: MedicationState, changes: MedicationChanges) -> UpdatePlan:
    """Lập kế hoạch cho PATCH theo bảng quy tắc của contract."""
    sent = changes.sent
    if not sent:
        raise _violation()
    if "stopped" in sent:
        if sent != {"stopped"}:
            raise _violation()
        if changes.stopped:
            if state.stopped:
                return UpdatePlan()
            return UpdatePlan(close_open_schedules=True, stop=True)
        # stopped: false = dùng lại; thuốc đang dùng thì không đổi gì (gửi lại an toàn).
        return UpdatePlan(reactivate=True) if state.stopped else UpdatePlan()
    if state.stopped:
        raise DomainError(STOPPED)

    target = changes.dosing_mode if "dosing_mode" in sent else state.dosing_mode
    switching = target is not state.dosing_mode
    if target is DosingMode.SCHEDULED and "max_doses_per_day" in sent:
        raise _violation()
    if target is DosingMode.AS_NEEDED and "intake_times" in sent:
        raise _violation()

    fields: dict[str, Any] = {}
    for name in ("quantity_per_dose", "intake_timing", "stock_quantity"):
        if name in sent:
            fields[name] = getattr(changes, name)

    if switching:
        fields["dosing_mode"] = target
    if target is DosingMode.SCHEDULED:
        if switching and "intake_times" not in sent:
            raise _violation()
        if "intake_times" not in sent:
            return UpdatePlan(fields=fields)
        times = tuple(sorted(changes.intake_times or ()))
        days = ALL_WEEK if switching else (state.open_days_of_week or ALL_WEEK)
        fields["doses_per_day"] = len(times)
        return UpdatePlan(
            fields=fields,
            close_open_schedules=True,
            new_intake_times=times,
            new_days_of_week=days,
        )
    # target là AS_NEEDED
    if switching and "max_doses_per_day" not in sent:
        raise _violation()
    if "max_doses_per_day" in sent:
        fields["doses_per_day"] = changes.max_doses_per_day
    return UpdatePlan(fields=fields, close_open_schedules=switching)
