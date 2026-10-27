from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest

from drugtime.modules.adherence import api
from drugtime.modules.adherence.application.scan_missed_doses import scan, scan_and_notify
from drugtime.modules.adherence.domain.dose import LATE_CONFIRMATION_WINDOW
from drugtime.shared.config import Settings

NOW = datetime(2026, 10, 19, 12, tzinfo=UTC)
PATIENT, FAMILY = uuid4(), uuid4()


def ports(occurrences=(), previous=None):
    return dict(
        now=NOW,
        grace=LATE_CONFIRMATION_WINDOW,
        overlap=timedelta(minutes=30),
        cursor=Mock(get=Mock(return_value=previous)),
        schedules=Mock(
            occurrences_between=Mock(return_value=list(occurrences)),
            alert_context=Mock(return_value="Test medication"),
        ),
        dose_logs=Mock(mark_missed=Mock(return_value=1)),
        access=Mock(caregivers_of=Mock(return_value=[FAMILY])),
        tokens=Mock(android_tokens=Mock(return_value=[(FAMILY, "unit-device-token")])),
        notifications=Mock(create_missed_alert=Mock(return_value=uuid4())),
        patient_names=Mock(get_patient_name=Mock(return_value="Test patient")),
        # Patient đã đồng bộ sau hạn chót: nhánh đã xác minh như 3.20 (3.19).
        checkpoints=Mock(get_many=Mock(return_value={PATIENT: NOW})),
        pending=Mock(add=Mock(return_value=True), verified=Mock(return_value=[])),
    )


def occurrence(minutes, microseconds=0, schedule_id=1):
    return SimpleNamespace(
        schedule_id=schedule_id,
        patient_id=PATIENT,
        scheduled_at=NOW - timedelta(minutes=minutes, microseconds=microseconds),
    )


def test_worker_default_is_120(monkeypatch):
    monkeypatch.delenv("MISSED_DOSE_GRACE_MINUTES", raising=False)
    assert Settings(_env_file=None).missed_dose_grace_minutes == 120


@pytest.mark.parametrize("minutes", [30, 60, 180])
def test_wrapper_rejects_30_60_180_before_uow(monkeypatch, minutes):
    settings = Settings(_env_file=None, missed_dose_grace_minutes=minutes)
    monkeypatch.setattr(api, "get_settings", lambda: settings)
    factory, notifier = Mock(), Mock()
    with pytest.raises(ValueError, match="must_be_120"):
        api.scan_missed_doses(factory, notifier=notifier)
    factory.assert_not_called()
    notifier.send.assert_not_called()


def test_api_settings_still_load_legacy_worker_override(monkeypatch):
    monkeypatch.setenv("MISSED_DOSE_GRACE_MINUTES", "60")
    assert Settings(_env_file=None).missed_dose_grace_minutes == 60


@pytest.mark.parametrize("minutes", [30, 60, 180])
def test_scan_rejects_wrong_grace_before_ports(minutes):
    args = ports()
    args["grace"] = timedelta(minutes=minutes)
    with pytest.raises(ValueError, match="must_be_120"):
        scan(object(), **args)
    for value in args.values():
        if isinstance(value, Mock):
            assert value.mock_calls == []
    factory = Mock()
    with pytest.raises(ValueError, match="must_be_120"):
        scan_and_notify(factory, Mock(), **args)
    factory.assert_not_called()


def test_scan_skips_occurrences_through_exact_120_and_marks_only_after():
    expired = occurrence(120, 1, 4)
    args = ports([occurrence(30), occurrence(60), occurrence(120), expired])
    alerts = scan(object(), **args).alerts
    assert len(alerts) == 1
    assert args["dose_logs"].mark_missed.call_count == 1
    assert args["dose_logs"].mark_missed.call_args.args[1:] == (4, expired.scheduled_at)
    assert args["notifications"].create_missed_alert.call_count == 1


def test_scan_only_pending_occurrences_does_not_create_alerts():
    args = ports([occurrence(120)])
    assert scan(object(), **args).alerts == []
    args["dose_logs"].mark_missed.assert_not_called()
    args["access"].caregivers_of.assert_not_called()
    args["notifications"].create_missed_alert.assert_not_called()


@pytest.mark.parametrize("offset", [None, 10, -10])
def test_ahead_cursor_does_not_invert_window_or_move_back(offset):
    horizon = NOW - LATE_CONFIRMATION_WINDOW
    previous = None if offset is None else horizon + timedelta(minutes=offset)
    args = ports(previous=previous)
    scan(object(), **args)
    start, end = args["schedules"].occurrences_between.call_args.args[1:]
    assert start <= end == horizon
    assert start == min(previous or horizon, horizon) - timedelta(minutes=30)
    assert args["cursor"].advance.call_args.args[1] == max(previous or horizon, horizon)


def test_worker_does_not_overwrite_confirmed_or_duplicate_notifications():
    args = ports([occurrence(121)])
    args["dose_logs"].mark_missed.return_value = None  # SQL port reports existing confirmed/missed.
    assert scan(object(), **args).alerts == []
    args["notifications"].create_missed_alert.assert_not_called()
    assert not args["dose_logs"].upsert_confirmation.called

    args = ports([occurrence(121)])
    args["notifications"].create_missed_alert.return_value = None
    args["tokens"].android_tokens.return_value = []
    assert scan(object(), **args).alerts == []
    assert args["tokens"].android_tokens.call_args.args[1] == []


@pytest.mark.parametrize("commit_failure", [False, True])
def test_notifications_are_sent_only_after_commit(commit_failure):
    events = []

    @contextmanager
    def transaction():
        events.append("begin")
        yield object()
        if commit_failure:
            raise RuntimeError("commit failed")
        events.append("commit")

    notifier = Mock(send=Mock(side_effect=lambda alerts: events.append("send")))
    args = ports([occurrence(121)])
    if commit_failure:
        with pytest.raises(RuntimeError, match="commit failed"):
            scan_and_notify(transaction, notifier, **args)
        assert events == ["begin"]
        notifier.send.assert_not_called()
    else:
        assert scan_and_notify(transaction, notifier, **args) == 1
        assert events == ["begin", "commit", "send"]


def test_wrapper_forwards_standard_window(monkeypatch):
    monkeypatch.setattr(
        api, "get_settings", lambda: Settings(_env_file=None, missed_dose_grace_minutes=120)
    )
    scanner = Mock(return_value=0)
    monkeypatch.setattr(api._scan, "scan_and_notify", scanner)
    assert api.scan_missed_doses(Mock(), notifier=Mock()) == 0
    assert scanner.call_args.kwargs["grace"] == LATE_CONFIRMATION_WINDOW
