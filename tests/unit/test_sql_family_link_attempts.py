"""SqlLinkAttempts (task 3.13): câu SQL, transaction riêng khi ghi lượt sai, không cần DB thật."""

import inspect
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

from drugtime.modules.family.adapters.outbound import sql_link_attempts
from drugtime.modules.family.adapters.outbound.sql_link_attempts import SqlLinkAttempts
from drugtime.modules.family.domain.link_request import LinkRequestLimits
from drugtime.modules.family.domain.throttle import ThrottleState

NOW = datetime(2026, 10, 16, 3, 0, tzinfo=UTC)


class FakeResult:
    def __init__(self, row):
        self.row = row

    def one(self):
        return self.row


class FakeConnection:
    def __init__(self, rows=()):
        self.rows = list(rows)
        self.calls = []

    def execute(self, statement, params=None):
        self.calls.append((" ".join(str(statement).split()), params or {}))
        return FakeResult(self.rows.pop(0) if self.rows else None)


class FakeUow:
    def __init__(self, rows=()):
        self.connection = FakeConnection(rows)


def _own_transactions(monkeypatch):
    """Thay pool riêng của lượt sai; mỗi phần tử của `opened` là một transaction đã mở."""
    opened = []

    class FakeEngine:
        @contextmanager
        def begin(self):
            uow = FakeUow()
            opened.append(uow)
            yield uow.connection

    monkeypatch.setattr(sql_link_attempts, "_failure_engine", lambda: FakeEngine())
    return opened


def test_state_maps_row__AC10():
    family, key = uuid4(), uuid4()
    until = NOW + timedelta(minutes=9)
    uow = FakeUow([SimpleNamespace(failures=5, locked_until=until, client_uuid_failed=True)])

    state = SqlLinkAttempts().state(uow, family, key, NOW, LinkRequestLimits())

    assert state == ThrottleState(failures_in_window=5, locked_until=until, client_uuid_failed=True)


def test_state_scans_only_window__AC11():
    family, key = uuid4(), uuid4()
    uow = FakeUow([SimpleNamespace(failures=0, locked_until=None, client_uuid_failed=False)])

    SqlLinkAttempts().state(uow, family, key, NOW, LinkRequestLimits())

    sql, params = uow.connection.calls[0]
    assert "count(*) FILTER (WHERE attempted_at > :window_start) AS failures" in sql
    assert "max(account_locked_until) FILTER (WHERE account_locked_until > :now)" in sql
    assert "WHERE family_user_id = :family_id AND client_uuid = :client_uuid" in sql
    assert sql.endswith("WHERE family_user_id = :family_id AND attempted_at > :scan_from")
    assert params == {
        "family_id": family,
        "client_uuid": key,
        "now": NOW,
        "window_start": NOW - timedelta(minutes=15),
        "scan_from": NOW - timedelta(minutes=15),
    }


def test_state_scan_covers_lock_longer_than_window__AC10():
    limits = LinkRequestLimits(fail_window=timedelta(minutes=15), lock_duration=timedelta(hours=1))
    uow = FakeUow([SimpleNamespace(failures=0, locked_until=None, client_uuid_failed=False)])

    SqlLinkAttempts().state(uow, uuid4(), uuid4(), NOW, limits)

    params = uow.connection.calls[0][1]
    assert params["window_start"] == NOW - timedelta(minutes=15)
    assert params["scan_from"] == NOW - timedelta(hours=1)


def test_record_failure_uses_own_unit_of_work__AC12(monkeypatch):
    opened = _own_transactions(monkeypatch)
    family, key = uuid4(), uuid4()
    until = NOW + timedelta(minutes=15)

    SqlLinkAttempts().record_failure(family, key, NOW, until)

    assert len(opened) == 1
    sql, params = opened[0].connection.calls[0]
    assert sql.startswith("INSERT INTO link_request_attempts")
    assert params == {
        "family_id": family,
        "client_uuid": key,
        "attempted_at": NOW,
        "locked_until": until,
    }


def test_record_failure_on_conflict_do_nothing__AC31(monkeypatch):
    opened = _own_transactions(monkeypatch)

    SqlLinkAttempts().record_failure(uuid4(), uuid4(), NOW, None)

    sql = opened[0].connection.calls[0][0]
    assert sql.endswith("ON CONFLICT (family_user_id, client_uuid) DO NOTHING")


def test_record_failure_params_have_no_code__AC18(monkeypatch):
    opened = _own_transactions(monkeypatch)

    SqlLinkAttempts().record_failure(uuid4(), uuid4(), NOW, None)

    sql, params = opened[0].connection.calls[0]
    assert "code" not in sql.replace("client_uuid", "")
    assert set(params) == {"family_id", "client_uuid", "attempted_at", "locked_until"}
    signature = inspect.signature(SqlLinkAttempts.record_failure)
    assert "code" not in signature.parameters


def test_failure_engine_is_separate_small_pool__AC13():
    """Lượt sai không lấy kết nối từ pool chính mà request đợi khóa người gửi đang giữ (H1)."""
    from drugtime.shared.db import get_engine

    sql_link_attempts._failure_engine.cache_clear()
    try:
        engine = sql_link_attempts._failure_engine()

        assert engine is not get_engine()
        assert engine is sql_link_attempts._failure_engine()
        assert engine.pool.size() == 2
        assert engine.pool._max_overflow == 3
    finally:
        sql_link_attempts._failure_engine().dispose()
        sql_link_attempts._failure_engine.cache_clear()
