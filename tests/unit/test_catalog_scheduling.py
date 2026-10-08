from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

from drugtime.modules.catalog import api
from drugtime.modules.catalog.application.scheduling import SYNC_INTERVAL, is_sync_due
from drugtime.modules.catalog.service import run_sync

NOW = datetime(2026, 10, 5, 4, 0, tzinfo=UTC)


class FakeRepository:
    def __init__(self, *, running=False, last_success_at=None, run_id=1):
        self.running = running
        self.last_success = last_success_at
        self.run_id = run_id

    def is_running(self, _uow, _source):
        return self.running

    def latest_success_at(self, _uow, _source):
        return self.last_success

    def start_run(self, _uow, _source, _triggered_by):
        return self.run_id


@contextmanager
def fake_uow():
    yield object()


def test_sync_due_when_no_successful_run():
    assert is_sync_due(None, NOW)


def test_sync_due_at_exactly_seven_days():
    assert is_sync_due(NOW - SYNC_INTERVAL, NOW)


def test_sync_not_due_before_seven_days():
    assert not is_sync_due(NOW - SYNC_INTERVAL + timedelta(seconds=1), NOW)


def test_sync_policy_rejects_naive_datetimes():
    naive = datetime(2026, 10, 5, 4, 0)
    try:
        is_sync_due(None, naive)
    except ValueError as exc:
        assert str(exc) == "now must be timezone-aware"
    else:
        raise AssertionError("naive datetime must be rejected")


def test_sync_if_due_enqueues_scheduler_task_once():
    sent = []

    result = api.sync_if_due(
        fake_uow,
        repository=FakeRepository(last_success_at=NOW - SYNC_INTERVAL),
        enqueue=lambda source, **kwargs: sent.append((source, kwargs)) or "job-1",
        now_fn=lambda: NOW,
    )

    assert result == "job-1"
    assert sent == [("dav_drugbank", {"triggered_by": "scheduler"})]


def test_sync_if_due_skips_when_not_due():
    sent = []

    result = api.sync_if_due(
        fake_uow,
        repository=FakeRepository(last_success_at=NOW - timedelta(days=1)),
        enqueue=lambda *args, **kwargs: sent.append((args, kwargs)),
        now_fn=lambda: NOW,
    )

    assert result is None
    assert sent == []


def test_sync_if_due_skips_when_source_is_running():
    sent = []

    result = api.sync_if_due(
        fake_uow,
        repository=FakeRepository(running=True),
        enqueue=lambda *args, **kwargs: sent.append((args, kwargs)),
        now_fn=lambda: NOW,
    )

    assert result is None
    assert sent == []


def test_run_sync_stops_when_running_slot_is_not_acquired():
    fetched = []

    run_sync(
        fake_uow,
        source="dav_drugbank",
        fetch=lambda: fetched.append(True) or [],
        parse=lambda _payload: [],
        repository=FakeRepository(run_id=None),
    )

    assert fetched == []
