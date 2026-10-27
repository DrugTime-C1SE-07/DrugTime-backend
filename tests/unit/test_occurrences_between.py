"""Task 3.19 (P4): tham số và câu SQL sinh lượt uống. Ngữ nghĩa trên DB thật nằm ở test tích hợp."""

from datetime import UTC, date, datetime, time, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest

from drugtime.modules.medication.adapters.outbound.sql_medication import (
    SqlMedication,
    _window_params,
)
from drugtime.modules.medication.domain.schedule import DoseOccurrence

VN = timezone(timedelta(hours=7))


class FakeConnection:
    def __init__(self, rows=()):
        self.rows = list(rows)
        self.calls = []

    def execute(self, statement, params=None):
        self.calls.append((str(statement), params or {}))
        return iter(self.rows)


class FakeUow:
    def __init__(self, connection):
        self.connection = connection


def test_naive_bounds_raise__AC9():
    with pytest.raises(ValueError):
        _window_params(datetime(2026, 10, 5, 0, 0), datetime(2026, 10, 5, 2, 0, tzinfo=UTC))
    with pytest.raises(ValueError):
        SqlMedication().occurrences_between(
            FakeUow(FakeConnection()),
            datetime(2026, 10, 5, 0, 0, tzinfo=UTC),
            datetime(2026, 10, 5, 2, 0),
        )


def test_empty_window_returns_empty_without_query__AC9():
    connection = FakeConnection()
    at = datetime(2026, 10, 5, 1, 0, tzinfo=UTC)

    assert SqlMedication().occurrences_between(FakeUow(connection), at, at) == []
    assert SqlMedication().occurrences_between(FakeUow(connection), at, at - timedelta(1)) == []
    assert connection.calls == []


def test_sql_binds_half_open_bounds_and_reminder_filter__AC2_AC3_AC12():
    connection = FakeConnection()
    start = datetime(2026, 10, 5, 0, 0, tzinfo=UTC)
    end = datetime(2026, 10, 5, 2, 0, tzinfo=UTC)

    SqlMedication().occurrences_between(FakeUow(connection), start, end)

    sql, params = connection.calls[0]
    assert params["start_at"] == start and params["end_at"] == end
    assert "occ.scheduled_at >= :start_at AND occ.scheduled_at < :end_at" in sql
    assert "occ.scheduled_at >= c.effective_from" in sql
    assert "occ.scheduled_at < c.ended_at" in sql
    assert "WHERE ms.reminder_enabled" in sql


def test_vietnam_date_and_isodow_params__AC6():
    # 06:00 VN Thứ Hai 05/10 = 23:00Z Chủ Nhật 04/10: ngày và thứ phải theo giờ VN.
    params = _window_params(
        datetime(2026, 10, 4, 22, 0, tzinfo=UTC), datetime(2026, 10, 5, 0, 0, tzinfo=UTC)
    )

    assert params["from_date"] == date(2026, 10, 4)
    assert params["to_date"] == date(2026, 10, 5)
    assert params["timezone"] == "Asia/Ho_Chi_Minh"
    assert params["prefilter"] == "same_day"
    assert (params["t_start"], params["t_end"]) == (time(5, 0), time(7, 0))


def test_intake_seconds_kept_in_time_bounds__AC7():
    params = _window_params(
        datetime(2026, 10, 5, 1, 0, 30, tzinfo=UTC), datetime(2026, 10, 5, 1, 0, 31, tzinfo=UTC)
    )

    assert (params["t_start"], params["t_end"]) == (time(8, 0, 30), time(8, 0, 31))


def test_window_params_same_day_and_cross_midnight__AC11():
    same = _window_params(
        datetime(2026, 10, 5, 7, 30, tzinfo=VN), datetime(2026, 10, 5, 8, 1, tzinfo=VN)
    )
    cross = _window_params(
        datetime(2026, 10, 5, 23, 50, tzinfo=VN), datetime(2026, 10, 6, 0, 10, tzinfo=VN)
    )
    day = _window_params(
        datetime(2026, 10, 5, 0, 0, tzinfo=VN), datetime(2026, 10, 6, 0, 0, tzinfo=VN)
    )

    assert same["prefilter"] == "same_day"
    assert cross["prefilter"] == "cross_midnight"
    assert (cross["t_start"], cross["t_end"]) == (time(23, 50), time(0, 10))
    assert day["prefilter"] is None and "t_start" not in day


@pytest.mark.parametrize(
    ("prefilter", "fragment"),
    [
        ("same_day", "ms.intake_time >= :t_start AND ms.intake_time < :t_end"),
        ("cross_midnight", "(ms.intake_time >= :t_start OR ms.intake_time < :t_end)"),
    ],
)
def test_prefilter_rendered_in_sql__AC11(prefilter, fragment):
    connection = FakeConnection()
    start = datetime(2026, 10, 5, 7, 30, tzinfo=VN)
    end = (
        datetime(2026, 10, 5, 8, 1, tzinfo=VN)
        if prefilter == "same_day"
        else datetime(2026, 10, 6, 0, 10, tzinfo=VN)
    )

    SqlMedication().occurrences_between(FakeUow(connection), start, end)

    sql, params = connection.calls[0]
    assert fragment in sql
    assert "prefilter" not in params


def test_ordering_and_maps_rows__AC8():
    patient = uuid4()
    at = datetime(2026, 10, 5, 1, 0, tzinfo=UTC)
    connection = FakeConnection(
        [SimpleNamespace(schedule_id=7, patient_id=patient, scheduled_at=at)]
    )

    result = SqlMedication().occurrences_between(
        FakeUow(connection), at - timedelta(hours=1), at + timedelta(days=3)
    )

    assert result == [DoseOccurrence(schedule_id=7, patient_id=patient, scheduled_at=at)]
    assert "ORDER BY occ.scheduled_at, c.schedule_id" in connection.calls[0][0]
