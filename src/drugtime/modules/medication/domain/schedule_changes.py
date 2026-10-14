"""Thêm, sửa, hủy từng lịch và mốc hiệu lực khi thay lịch (task 2.04). Hàm thuần, không I/O.

Lịch có hiệu lực trong khoảng nửa mở [effective_from, ended_at) (QD-16). Mọi hàm nhận mốc `at`
lấy sau khi khóa dòng thuốc và `latest_recorded`: giờ dự kiến muộn nhất của liều đã ghi với giờ
dự kiến >= at, theo id lịch (liều xác nhận sớm).
"""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, time, timedelta

from drugtime.modules.medication.domain.user_medication import (
    ALL_WEEK,
    RULE_VIOLATION,
    STOPPED,
    DosingMode,
    MedicationState,
    PendingClosed,
    ScheduleView,
)
from drugtime.shared.errors import DomainError, NotFound

MAX_SCHEDULES = 6

SCHEDULE_NOT_FOUND = "medication_schedule_not_found"
TIME_CONFLICT = "schedule_time_conflict"
LIMIT_REACHED = "schedule_limit_reached"
LAST_NOT_REMOVABLE = "last_schedule_not_removable"

# Lịch cũ kết thúc ngay sau giờ dự kiến của liều xác nhận sớm, để liều vẫn thuộc lịch cũ.
AFTER_RECORDED = timedelta(seconds=1)


@dataclass(frozen=True)
class NewSchedule:
    intake_time: time
    days_of_week: tuple[int, ...]
    reminder_enabled: bool
    effective_from: datetime


@dataclass(frozen=True)
class ClosedSchedule:
    """Lịch đã đóng, ứng viên để mở lại khi dùng lại thuốc đã ngừng."""

    id: int
    intake_time: time
    days_of_week: tuple[int, ...]
    reminder_enabled: bool
    effective_from: datetime
    ended_at: datetime


@dataclass(frozen=True)
class ScheduleWrite:
    close: tuple[tuple[int, datetime], ...] = ()  # (id lịch, ended_at)
    insert: tuple[NewSchedule, ...] = ()
    doses_per_day: int | None = None  # None = không đổi

    @property
    def is_noop(self) -> bool:
        return not (self.close or self.insert or self.doses_per_day is not None)


def close_at(schedule: ScheduleView, at: datetime, latest_recorded: datetime | None) -> datetime:
    """ended_at khi đóng lịch: không trước `at`, không trước effective_from (CHECK của bảng),
    và sau liều đã ghi muộn nhất của lịch."""
    end = max(at, schedule.effective_from)
    if latest_recorded is not None:
        end = max(end, latest_recorded + AFTER_RECORDED)
    return end


def start_at(
    at: datetime,
    replaced_ends: Iterable[datetime],
    pending: Iterable[PendingClosed],
    intake_time: time,
) -> datetime:
    """effective_from của lịch mới: sau mọi lịch nó thay, và sau lịch cùng giờ vừa đóng mà
    ended_at còn ở tương lai, để một lượt uống không thuộc hai lịch."""
    start = max([at, *replaced_ends])
    for p in pending:
        if p.intake_time == intake_time:
            start = max(start, p.ended_at)
    return start


def replace_all(
    state: MedicationState,
    at: datetime,
    latest_recorded: Mapping[int, datetime],
    intake_times: tuple[time, ...],
    days_of_week: tuple[int, ...],
    reminders: tuple[bool, ...],
) -> ScheduleWrite:
    """Đóng mọi lịch đang mở và tạo bộ lịch mới (đổi giờ hoặc đổi ngày của cả thuốc)."""
    close = tuple((s.id, close_at(s, at, latest_recorded.get(s.id))) for s in state.open_schedules)
    ends = [end for _, end in close]
    insert = tuple(
        NewSchedule(t, days_of_week, r, start_at(at, ends, state.pending_closed, t))
        for t, r in zip(intake_times, reminders, strict=True)
    )
    return ScheduleWrite(close=close, insert=insert)


def close_all(
    state: MedicationState, at: datetime, latest_recorded: Mapping[int, datetime]
) -> tuple[tuple[int, datetime], ...]:
    """Đóng mọi lịch đang mở, không có lịch thay thế (ngừng, chuyển khi cần, xoá thuốc).
    Lịch có liều xác nhận sớm đóng sau liều đó, như mọi đường đóng lịch khác (QD-16, R1)."""
    return tuple((s.id, close_at(s, at, latest_recorded.get(s.id))) for s in state.open_schedules)


def pick_reactivation(candidates: Sequence[ClosedSchedule]) -> tuple[ClosedSchedule, ...]:
    """Lịch mở lại khi dùng lại thuốc: `candidates` là các lịch mang dấu đóng bởi lần ngừng gần
    nhất (closed_by_stop_at, task 2.04 vòng 4). Giữ một lịch mỗi giờ (id lớn nhất) để phòng thủ;
    bình thường các giờ đã khác nhau vì lịch mở không trùng giờ."""
    picked: dict[time, ClosedSchedule] = {}
    for x in sorted(candidates, key=lambda c: c.id):
        picked[x.intake_time] = x
    return tuple(sorted(picked.values(), key=lambda c: (c.intake_time, c.id)))


def plan_reactivation(
    state: MedicationState, at: datetime, picked: Sequence[ClosedSchedule]
) -> ScheduleWrite:
    """Mở lại lịch đã chọn; lịch cùng giờ vừa đóng còn hiệu lực thì bắt đầu sau nó (R2)."""
    return ScheduleWrite(
        insert=tuple(
            NewSchedule(
                c.intake_time,
                c.days_of_week,
                c.reminder_enabled,
                start_at(at, (), state.pending_closed, c.intake_time),
            )
            for c in picked
        )
    )


def _open(state: MedicationState, schedule_id: int) -> ScheduleView:
    for s in state.open_schedules:
        if s.id == schedule_id:
            return s
    raise NotFound(SCHEDULE_NOT_FOUND)


def plan_add(
    state: MedicationState, at: datetime, intake_time: time, reminder_enabled: bool
) -> ScheduleWrite:
    if state.stopped:
        raise DomainError(STOPPED)
    if state.dosing_mode is DosingMode.AS_NEEDED:
        raise DomainError(RULE_VIOLATION)
    if any(s.intake_time == intake_time for s in state.open_schedules):
        raise DomainError(TIME_CONFLICT)
    if len(state.open_schedules) >= MAX_SCHEDULES:
        raise DomainError(LIMIT_REACHED)
    days = state.open_days_of_week or ALL_WEEK
    start = start_at(at, (), state.pending_closed, intake_time)
    return ScheduleWrite(
        insert=(NewSchedule(intake_time, days, reminder_enabled, start),),
        doses_per_day=len(state.open_schedules) + 1,
    )


def plan_edit(
    state: MedicationState,
    at: datetime,
    schedule_id: int,
    latest_recorded: Mapping[int, datetime],
    *,
    intake_time: time | None = None,
    reminder_enabled: bool | None = None,
) -> ScheduleWrite:
    """None = field không gửi. Giá trị giống hệt hiện tại thì không làm gì."""
    if state.stopped:
        raise DomainError(STOPPED)
    old = _open(state, schedule_id)
    new_time = old.intake_time if intake_time is None else intake_time
    new_reminder = old.reminder_enabled if reminder_enabled is None else reminder_enabled
    if (new_time, new_reminder) == (old.intake_time, old.reminder_enabled):
        return ScheduleWrite()
    if any(s.id != old.id and s.intake_time == new_time for s in state.open_schedules):
        raise DomainError(TIME_CONFLICT)
    end = close_at(old, at, latest_recorded.get(old.id))
    start = start_at(at, (end,), state.pending_closed, new_time)
    return ScheduleWrite(
        close=((old.id, end),),
        insert=(NewSchedule(new_time, old.days_of_week, new_reminder, start),),
    )


def plan_remove(
    state: MedicationState,
    at: datetime,
    schedule_id: int,
    latest_recorded: Mapping[int, datetime],
) -> ScheduleWrite:
    if state.stopped:
        raise DomainError(STOPPED)
    old = _open(state, schedule_id)
    if len(state.open_schedules) == 1:
        raise DomainError(LAST_NOT_REMOVABLE)
    return ScheduleWrite(
        close=((old.id, close_at(old, at, latest_recorded.get(old.id))),),
        doses_per_day=len(state.open_schedules) - 1,
    )
