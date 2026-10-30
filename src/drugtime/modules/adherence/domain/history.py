"""Lịch sử tuân thủ: thời gian, nhóm và tỷ lệ, không phụ thuộc hạ tầng."""

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum
from uuid import UUID
from zoneinfo import ZoneInfo

from drugtime.modules.adherence.domain.dose import LATE_CONFIRMATION_WINDOW, DoseStatus
from drugtime.shared.errors import DomainError

TIMEZONE = "Asia/Ho_Chi_Minh"
VIETNAM = ZoneInfo(TIMEZONE)


class GroupBy(StrEnum):
    DATE = "date"
    MEDICATION = "medication"


@dataclass(frozen=True)
class HistoryRange:
    start: date
    end: date


def resolve_range(start: date | None, end: date | None, as_of: datetime) -> HistoryRange:
    today = as_of.astimezone(VIETNAM).date()
    end = end if end is not None else today
    if start is None:
        if end < date.min + timedelta(days=29):
            raise DomainError("invalid_adherence_date_range")
        start = end - timedelta(days=29)
    if start > end:
        raise DomainError("invalid_adherence_date_range")
    if (end - start).days >= 90:
        raise DomainError("adherence_range_too_large")
    if end > today:
        raise DomainError("adherence_end_date_in_future")
    return HistoryRange(start, end)


@dataclass(frozen=True)
class HistoryRow:
    medication_id: int
    medication_name: str
    schedule_id: int
    scheduled_at: datetime
    taken_at: datetime | None
    status: DoseStatus | None


@dataclass(frozen=True)
class HistoryDose:
    medication_id: int
    medication_name: str
    schedule_id: int
    scheduled_at: datetime
    taken_at: datetime | None
    status: str
    status_source: str


def dose_view(row: HistoryRow, as_of: datetime, synced_at: datetime | None) -> HistoryDose:
    """synced_at: checkpoint đồng bộ của patient. Liều quá hạn chót chưa có dòng mà patient chưa
    đồng bộ kể từ hạn chót là chua_xac_minh (3.19, chỉ hiển thị, BS-01); đã đồng bộ thì bo_lo."""
    deadline = row.scheduled_at + LATE_CONFIRMATION_WINDOW
    if row.status in (DoseStatus.TAKEN, DoseStatus.LATE):
        if row.taken_at is None:
            raise ValueError("confirmed_dose_missing_timestamp")
        status, source, taken_at = row.status.value, "recorded", row.taken_at
    elif as_of <= deadline:
        status, source, taken_at = "cho_xac_nhan", "inferred", None
    elif row.status is None and (synced_at is None or synced_at < deadline):
        status, source, taken_at = "chua_xac_minh", "inferred", None
    else:
        status = DoseStatus.MISSED.value
        source = "recorded" if row.status is DoseStatus.MISSED else "inferred"
        taken_at = None
    return HistoryDose(
        medication_id=row.medication_id,
        medication_name=row.medication_name,
        schedule_id=row.schedule_id,
        scheduled_at=row.scheduled_at.astimezone(VIETNAM),
        taken_at=taken_at.astimezone(VIETNAM) if taken_at is not None else None,
        status=status,
        status_source=source,
    )


@dataclass(frozen=True)
class Summary:
    total: int
    taken: int
    late: int
    missed: int
    pending: int
    unverified: int
    counted: int
    adherence_rate: Decimal | None


def summarize(doses: Iterable[HistoryDose]) -> Summary:
    statuses = ("da_uong", "uong_tre", "bo_lo", "cho_xac_nhan", "chua_xac_minh")
    counts = dict.fromkeys(statuses, 0)
    for dose in doses:
        counts[dose.status] += 1
    taken, late, missed, pending, unverified = counts.values()
    # Liều chờ xác nhận và chưa xác minh không vào mẫu số của tỷ lệ (A14).
    counted = taken + late + missed
    rate = (
        (Decimal(100) * (taken + late) / counted).quantize(Decimal("0.01"), ROUND_HALF_UP)
        if counted
        else None
    )
    return Summary(
        total=counted + pending + unverified,
        taken=taken,
        late=late,
        missed=missed,
        pending=pending,
        unverified=unverified,
        counted=counted,
        adherence_rate=rate,
    )


@dataclass(frozen=True)
class DateGroup:
    date: date
    summary: Summary
    doses: tuple[HistoryDose, ...]


@dataclass(frozen=True)
class MedicationGroup:
    medication_id: int
    medication_name: str
    summary: Summary
    doses: tuple[HistoryDose, ...]


@dataclass(frozen=True)
class History:
    patient_id: UUID
    start: date
    end: date
    timezone: str
    as_of: datetime
    patient_last_synced_at: datetime | None
    summary: Summary
    group_by: GroupBy
    groups: tuple[DateGroup | MedicationGroup, ...]


def build_history(
    rows: Iterable[HistoryRow],
    *,
    patient_id: UUID,
    period: HistoryRange,
    group_by: GroupBy,
    as_of: datetime,
    synced_at: datetime | None,
) -> History:
    doses = sorted(
        (
            dose_view(row, as_of, synced_at)
            for row in rows
            if row.scheduled_at <= as_of
            and period.start <= row.scheduled_at.astimezone(VIETNAM).date() <= period.end
        ),
        key=lambda dose: (dose.scheduled_at, dose.medication_id, dose.schedule_id),
    )
    groups: list[DateGroup | MedicationGroup] = []
    if group_by is GroupBy.DATE:
        by_date = defaultdict(list)
        for dose in doses:
            by_date[dose.scheduled_at.date()].append(dose)
        groups = [
            DateGroup(day, summarize(by_date[day]), tuple(by_date[day]))
            for day in sorted(by_date, reverse=True)
        ]
    else:
        by_medication = defaultdict(list)
        for dose in doses:
            by_medication[dose.medication_id].append(dose)
        groups = [
            MedicationGroup(
                mid,
                by_medication[mid][0].medication_name,
                summarize(by_medication[mid]),
                tuple(by_medication[mid]),
            )
            for mid in sorted(by_medication)
        ]
    return History(
        patient_id=patient_id,
        start=period.start,
        end=period.end,
        timezone=TIMEZONE,
        as_of=as_of.astimezone(VIETNAM),
        patient_last_synced_at=synced_at.astimezone(VIETNAM) if synced_at is not None else None,
        summary=summarize(doses),
        group_by=group_by,
        groups=tuple(groups),
    )
