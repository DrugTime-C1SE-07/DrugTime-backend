from contextlib import contextmanager
from datetime import UTC, datetime, time, timedelta
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest

from drugtime.modules.adherence.application.dispatch_patient_dose_reminders import (
    dispatch_reminders,
)
from drugtime.modules.adherence.domain.patient_dose_reminder import (
    ReminderRecord,
    ReminderTransportResult,
)
from drugtime.shared.errors import Forbidden


@contextmanager
def uow_factory():
    yield Mock()


@pytest.fixture
def dispatch():
    now = datetime(2026, 11, 19, 2, tzinfo=UTC)
    record = ReminderRecord(
        1,
        uuid4(),
        uuid4(),
        2,
        now - timedelta(minutes=30),
        now,
        now + timedelta(minutes=10),
        "accepted",
        91,
    )
    store, doses, schedules, access, tokens, notifier = [Mock() for _ in range(6)]
    store.claim.side_effect = [(record.id, now + timedelta(seconds=60)), None]
    store.leased.return_value = (record, 0, set())
    store.now.return_value = now
    doses.confirmed.return_value = False
    schedules.reminder_context.return_value = SimpleNamespace(
        patient_id=record.patient_id,
        intake_time=time(8, 30),
        days_of_week=(4,),
        effective_from=now - timedelta(days=2),
        ended_at=None,
        unavailable=False,
    )
    tokens.android_tokens.return_value = [(record.patient_id, "test-device")]
    notifier.send_reminder.return_value = ReminderTransportResult(True)
    return dict(
        store=store,
        doses=doses,
        schedules=schedules,
        access=access,
        tokens=tokens,
        notifier=notifier,
    )


def test_dispatch_revalidates_before_each_token_and_preserves_stable_id(dispatch):
    dispatch["tokens"].android_tokens.return_value *= 2
    assert dispatch_reminders(uow_factory, **dispatch) == 1
    assert dispatch["access"].authorize_history.call_count == 3
    assert all(
        call.args[0].reminder_id == 1 for call in dispatch["notifier"].send_reminder.call_args_list
    )
    finish = dispatch["store"].finish.call_args.kwargs
    assert finish["status"] == "dispatched" and finish["state"] == "done"
    assert finish["hashes"] and "test-device" not in finish["hashes"]


@pytest.mark.parametrize("blocked", ["revoked", "confirmed", "stopped"])
def test_ineligible_after_acceptance_never_sends(dispatch, blocked):
    if blocked == "revoked":
        dispatch["access"].authorize_history.side_effect = Forbidden("khong_co_quyen")
    elif blocked == "confirmed":
        dispatch["doses"].confirmed.return_value = True
    else:
        dispatch["schedules"].reminder_context.return_value.unavailable = True
    dispatch_reminders(uow_factory, **dispatch)
    dispatch["notifier"].send_reminder.assert_not_called()
    assert dispatch["store"].finish.call_args.kwargs["status"] == "cancelled"


def test_audit_failure_prevents_transport(dispatch):
    dispatch["access"].authorize_history.side_effect = RuntimeError("audit unavailable")
    with pytest.raises(RuntimeError):
        dispatch_reminders(uow_factory, **dispatch)
    dispatch["notifier"].send_reminder.assert_not_called()
    dispatch["store"].finish.assert_not_called()


def test_no_android_target_keeps_accepted_inbox_without_fake_delivery(dispatch):
    dispatch["tokens"].android_tokens.return_value = []
    dispatch_reminders(uow_factory, **dispatch)
    result = dispatch["store"].finish.call_args.kwargs
    assert (result["status"], result["state"], result["error"]) == (
        "accepted",
        "done",
        "no_targets",
    )
    dispatch["notifier"].send_reminder.assert_not_called()


@pytest.mark.parametrize(
    "attempts,delay,state,status",
    [(0, 30, "pending", "accepted"), (1, 120, "pending", "accepted"), (2, 0, "dead", "failed")],
)
def test_retry_backoff_and_exhaustion(dispatch, attempts, delay, state, status):
    record, _, hashes = dispatch["store"].leased.return_value
    dispatch["store"].leased.return_value = (record, attempts, hashes)
    dispatch["notifier"].send_reminder.return_value = ReminderTransportResult(False)
    dispatch_reminders(uow_factory, **dispatch)
    result = dispatch["store"].finish.call_args.kwargs
    assert (result["attempts"], result["delay"], result["state"], result["status"]) == (
        attempts + 1,
        delay,
        state,
        status,
    )


def test_stale_lease_does_not_send_or_mutate_reclaimed_job(dispatch):
    dispatch["store"].leased.return_value = None
    dispatch_reminders(uow_factory, **dispatch)
    dispatch["notifier"].send_reminder.assert_not_called()
    dispatch["store"].finish.assert_not_called()
    dispatch["store"].cleanup.assert_called_once()


def test_erasure_cleans_sender_and_patient_reminders_before_medication_references():
    from drugtime.modules.adherence.application.erase_user import erase_user

    events = []
    reminders, pending, schedules, doses, notifications, checkpoints = [Mock() for _ in range(6)]
    user = uuid4()
    reminders.cleanup.side_effect = lambda *a: events.append("reminders")
    pending.erase_for_patient.side_effect = lambda *a: events.append("pending")
    schedules.ids_of.return_value = [2]
    doses.erase_for_schedules.side_effect = lambda *a: events.append("doses")
    notifications.erase_for_user.side_effect = lambda *a: events.append("notifications")
    erase_user(
        None,
        user,
        schedules=schedules,
        dose_logs=doses,
        notifications=notifications,
        checkpoints=checkpoints,
        pending=pending,
        reminders=reminders,
    )
    reminders.cleanup.assert_called_once_with(None, user)
    assert events == ["reminders", "pending", "doses", "notifications"]
