from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

from drugtime.modules.adherence.adapters.outbound.sql_adherence import SqlDoseLogs
from drugtime.modules.adherence.domain.dose import ClientUuidConflict, DoseConfirmation, DoseStatus


class FakeResult:
    def __init__(self, row=None):
        self.row = row

    def first(self):
        return self.row

    def one(self):
        return self.row


class FakeConnection:
    def __init__(self, results):
        self.results = list(results)
        self.calls = []

    def execute(self, statement, params=None):
        self.calls.append((str(statement), params or {}))
        return FakeResult(self.results.pop(0))


class FakeUow:
    def __init__(self, connection):
        self.connection = connection


def _row(client_uuid, schedule_id=1, scheduled_at=None, taken_at=None, status="da_uong"):
    scheduled_at = scheduled_at or datetime(2026, 10, 2, 1, 0, tzinfo=UTC)
    if taken_at is None and status != "bo_lo":
        taken_at = datetime(2026, 10, 2, 1, 5, tzinfo=UTC)
    return SimpleNamespace(
        id=9001,
        client_uuid=client_uuid,
        medication_schedule_id=schedule_id,
        scheduled_at=scheduled_at,
        taken_at=taken_at,
        status=status,
        synced_at=datetime(2026, 10, 2, 1, 6, tzinfo=UTC),
    )


def test_upsert_confirmation_returns_existing_for_same_client_uuid_payload():
    # AC2: Retry cùng client_uuid và cùng payload phải trả bản ghi cũ, không insert lần hai.
    client_uuid = uuid4()
    scheduled_at = datetime(2026, 10, 2, 1, 0, tzinfo=UTC)
    taken_at = datetime(2026, 10, 2, 1, 5, tzinfo=UTC)
    connection = FakeConnection([_row(client_uuid)])
    c = DoseConfirmation(client_uuid, 1, scheduled_at, taken_at)

    result = SqlDoseLogs().upsert_confirmation(FakeUow(connection), c, DoseStatus.TAKEN)

    assert result.record.id == 9001
    assert result.adherence_counted is True
    assert len(connection.calls) == 1


def test_upsert_confirmation_rejects_same_client_uuid_different_payload():
    # AC2: Cùng client_uuid nhưng khác payload là conflict để chống sync nhầm liều.
    client_uuid = uuid4()
    connection = FakeConnection([_row(client_uuid, schedule_id=2)])
    c = DoseConfirmation(
        client_uuid,
        1,
        datetime(2026, 10, 2, 1, 0, tzinfo=UTC),
        datetime(2026, 10, 2, 1, 5, tzinfo=UTC),
    )

    with pytest.raises(ClientUuidConflict):
        SqlDoseLogs().upsert_confirmation(FakeUow(connection), c, DoseStatus.TAKEN)


def test_upsert_confirmation_inserts_with_schema_v11_status_value():
    # AC1/AC14: SQL adapter ghi đúng enum schema v11, ví dụ uong_tre thay vì text có dấu.
    client_uuid = uuid4()
    scheduled_at = datetime(2026, 10, 2, 1, 0, tzinfo=UTC)
    taken_at = datetime(2026, 10, 2, 1, 31, tzinfo=UTC)
    connection = FakeConnection([None, _row(client_uuid, status="uong_tre", taken_at=taken_at)])
    c = DoseConfirmation(client_uuid, 1, scheduled_at, taken_at)

    result = SqlDoseLogs().upsert_confirmation(FakeUow(connection), c, DoseStatus.LATE)

    assert result.record.status is DoseStatus.LATE
    assert result.adherence_counted is True
    assert connection.calls[1][1]["status"] == "uong_tre"


def test_upsert_confirmation_persists_missed_confirmation_without_taken_at():
    client_uuid = uuid4()
    c = DoseConfirmation(
        client_uuid,
        1,
        datetime(2026, 10, 2, 1, 0, tzinfo=UTC),
        datetime(2026, 10, 2, 3, 0, 0, 1, tzinfo=UTC),
    )
    connection = FakeConnection([None, _row(client_uuid, status="bo_lo", taken_at=None)])

    result = SqlDoseLogs().upsert_confirmation(FakeUow(connection), c, DoseStatus.MISSED)

    assert result.record.status is DoseStatus.MISSED
    assert result.record.taken_at is None
    assert result.adherence_counted is False
    assert connection.calls[1][1]["status"] == "bo_lo"
    assert connection.calls[1][1]["taken_at"] is None


class RowsConnection:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    def execute(self, statement, params=None):
        self.calls.append((str(statement), params or {}))
        return iter(self.rows)


def test_latest_at_or_after_groups_by_schedule():
    at = datetime(2026, 10, 9, 0, 50, tzinfo=UTC)
    latest = datetime(2026, 10, 9, 1, 0, tzinfo=UTC)
    conn = RowsConnection([SimpleNamespace(medication_schedule_id=7, latest=latest)])
    assert SqlDoseLogs().latest_at_or_after(FakeUow(conn), [7, 8], at) == {7: latest}
    sql, params = conn.calls[0]
    assert "scheduled_at >= :at" in sql and "GROUP BY medication_schedule_id" in sql
    assert params == {"ids": [7, 8], "at": at}


def test_latest_at_or_after_empty_ids_no_query():
    conn = RowsConnection([])
    assert SqlDoseLogs().latest_at_or_after(FakeUow(conn), [], datetime.now(UTC)) == {}
    assert conn.calls == []
