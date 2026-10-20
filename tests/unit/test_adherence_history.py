from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from drugtime.modules.adherence.domain.dose import (
    DoseConfirmation,
    DoseStatus,
    status_for_confirmation,
)
from drugtime.modules.adherence.domain.history import (
    VIETNAM,
    GroupBy,
    HistoryRange,
    HistoryRow,
    build_history,
    dose_view,
    resolve_range,
    summarize,
)
from drugtime.shared.errors import DomainError

AT = datetime(2026, 10, 19, 8, tzinfo=VIETNAM)
PATIENT = uuid4()
ROW = HistoryRow(1, "Medicine", 1, AT, None, None)
PERIOD = HistoryRange(date(2026, 10, 1), date(2026, 10, 19))


def history(rows, *, as_of=AT + timedelta(hours=3), group_by=GroupBy.DATE):
    return build_history(rows, patient_id=PATIENT, period=PERIOD, group_by=group_by, as_of=as_of)


def test_resolve_default_and_partial_date_range():
    assert resolve_range(None, None, AT) == HistoryRange(date(2026, 9, 20), AT.date())
    assert resolve_range(None, date(2026, 9, 30), AT).start == date(2026, 9, 1)
    assert resolve_range(date(2026, 10, 1), None, AT).end == AT.date()
    # UTC date differs from the fixed Vietnamese calendar date.
    assert resolve_range(None, None, datetime(2026, 10, 18, 18, tzinfo=UTC)).end == AT.date()


def test_inclusive_90_allowed_91_rejected():
    assert resolve_range(AT.date() - timedelta(days=89), AT.date(), AT)
    with pytest.raises(DomainError, match="adherence_range_too_large"):
        resolve_range(AT.date() - timedelta(days=90), AT.date(), AT)


@pytest.mark.parametrize(
    "start,end,error",
    [
        (date(2026, 10, 19), date(2026, 10, 18), "invalid_adherence_date_range"),
        (None, date(2026, 10, 20), "adherence_end_date_in_future"),
        (None, date.min, "invalid_adherence_date_range"),
    ],
)
def test_reversed_and_future_dates(start, end, error):
    with pytest.raises(DomainError, match=error):
        resolve_range(start, end, AT)


@pytest.mark.parametrize("minutes,us", [(0, 0), (30, 0), (30, 1), (90, 0), (120, 0)])
@pytest.mark.parametrize("status", [None, DoseStatus.MISSED])
def test_pending_at_30_after_30_and_exact_120(minutes, us, status):
    dose = dose_view(replace(ROW, status=status), AT + timedelta(minutes=minutes, microseconds=us))
    assert (dose.status, dose.status_source, dose.taken_at) == ("cho_xac_nhan", "inferred", None)


@pytest.mark.parametrize("status,source", [(None, "inferred"), (DoseStatus.MISSED, "recorded")])
def test_missed_one_microsecond_after_120(status, source):
    dose = dose_view(replace(ROW, status=status), AT + timedelta(minutes=120, microseconds=1))
    assert (dose.status, dose.status_source, dose.taken_at) == ("bo_lo", source, None)


@pytest.mark.parametrize(
    "delay,status",
    [
        (timedelta(minutes=30), DoseStatus.TAKEN),
        (timedelta(minutes=30, microseconds=1), DoseStatus.LATE),
        (timedelta(minutes=120), DoseStatus.LATE),
    ],
)
def test_recorded_confirmation_boundaries_30_and_120(delay, status):
    taken = AT + delay
    assert status_for_confirmation(DoseConfirmation(uuid4(), 1, AT, taken), taken) is status
    dose = dose_view(replace(ROW, status=status, taken_at=taken), taken + timedelta(days=1))
    assert (dose.status, dose.status_source, dose.taken_at) == (status.value, "recorded", taken)


def test_future_occurrences_including_early_confirmed_are_excluded():
    future = replace(
        ROW, scheduled_at=AT + timedelta(minutes=15), taken_at=AT, status=DoseStatus.TAKEN
    )
    assert history([future], as_of=AT).groups == ()


def test_recorded_status_and_timestamp_precision_preserved():
    row = replace(
        ROW,
        scheduled_at=AT.replace(microsecond=123456),
        taken_at=AT.replace(minute=1, microsecond=654321),
        status=DoseStatus.LATE,
    )
    dose = history([row]).groups[0].doses[0]
    assert dose.scheduled_at == row.scheduled_at and dose.taken_at == row.taken_at
    assert dose.status == "uong_tre"


def test_date_group_uses_vietnam_scheduled_date_across_midnight():
    scheduled = AT.replace(day=18, hour=23, minute=30)
    taken = AT.replace(hour=0, minute=15)
    dose = history(
        [
            replace(
                ROW, scheduled_at=scheduled.astimezone(UTC), taken_at=taken, status=DoseStatus.LATE
            )
        ]
    ).groups[0]
    assert dose.date == date(2026, 10, 18)
    assert dose.doses[0].taken_at.date() == date(2026, 10, 19)
    assert dose.doses[0].scheduled_at.isoformat().endswith("+07:00")


def test_stable_group_and_dose_order():
    rows = [
        replace(ROW, schedule_id=2),
        replace(ROW, schedule_id=1),
        replace(ROW, medication_id=2),
        replace(ROW, scheduled_at=AT - timedelta(days=1)),
    ]
    result = history(rows)
    assert [g.date for g in result.groups] == [AT.date(), date(2026, 10, 18)]
    assert [(d.medication_id, d.schedule_id) for d in result.groups[0].doses] == [
        (1, 1),
        (1, 2),
        (2, 1),
    ]


def test_medication_group_combines_entries_and_schedules_but_not_same_name_other_id():
    rows = [replace(ROW, medication_id=2), replace(ROW, schedule_id=2), ROW]
    result = history(rows, group_by=GroupBy.MEDICATION)
    assert [g.medication_id for g in result.groups] == [1, 2]
    assert [g.summary.total for g in result.groups] == [2, 1]


def test_rate_80_percent_and_overall_from_counts_not_group_average():
    rows = [replace(ROW, schedule_id=n, taken_at=AT, status=DoseStatus.TAKEN) for n in range(3)]
    rows += [
        replace(ROW, schedule_id=4, taken_at=AT + timedelta(hours=1), status=DoseStatus.LATE),
        replace(ROW, medication_id=2, status=DoseStatus.MISSED),
    ]
    result = history(rows, group_by=GroupBy.MEDICATION)
    assert result.summary.total == result.summary.counted == 5
    assert result.summary.adherence_rate == Decimal("80.00")
    assert [g.summary.adherence_rate for g in result.groups] == [Decimal(100), Decimal(0)]


def test_half_up_two_decimal_places():
    taken = dose_view(replace(ROW, status=DoseStatus.TAKEN, taken_at=AT), AT)
    missed = dose_view(ROW, AT + timedelta(hours=3))
    assert summarize([taken] + [missed] * 31).adherence_rate == Decimal("3.13")


def test_empty_and_pending_only_have_null_rate():
    assert history([]).summary.adherence_rate is None
    pending = history([ROW], as_of=AT)
    assert pending.summary.counted == 0 and pending.summary.pending == 1
    assert pending.summary.adherence_rate is None


def test_pending_rate_at_120_and_missed_rate_after_120():
    rows = [
        replace(ROW, status=DoseStatus.TAKEN, taken_at=AT),
        replace(ROW, schedule_id=2, scheduled_at=AT + timedelta(hours=2)),
    ]
    at_deadline = history(rows, as_of=AT + timedelta(hours=4))
    after = history(rows, as_of=AT + timedelta(hours=4, minutes=1))
    assert (at_deadline.summary.pending, at_deadline.summary.adherence_rate) == (1, Decimal(100))
    assert (after.summary.missed, after.summary.adherence_rate) == (1, Decimal(50))


def test_invalid_recorded_confirmation_fails_instead_of_counting_taken():
    with pytest.raises(ValueError, match="confirmed_dose_missing_timestamp"):
        dose_view(replace(ROW, status=DoseStatus.TAKEN), AT)
