from dataclasses import replace
from datetime import UTC, datetime, time, timedelta
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest

from drugtime.modules.adherence.application.patient_dose_reminders import (
    received_detail,
    received_list,
    send_reminder,
)
from drugtime.modules.adherence.domain.patient_dose_reminder import (
    ReminderCommand,
    ReminderRecord,
    validate_occurrence,
)
from drugtime.shared.errors import Conflict, DomainError, Forbidden, NotFound, TooManyRequests


@pytest.fixture
def setup():
    now = datetime(2026, 11, 19, 2, tzinfo=UTC)
    patient, caller = uuid4(), uuid4()
    cmd = ReminderCommand(uuid4(), 5, now - timedelta(minutes=30))
    context = SimpleNamespace(
        patient_id=patient,
        intake_time=time(8, 30),
        days_of_week=(1, 2, 3, 4, 5, 6, 7),
        effective_from=now - timedelta(days=60),
        ended_at=None,
        unavailable=False,
    )
    record = ReminderRecord(
        1, caller, patient, 5, cmd.scheduled_at, now, now + timedelta(seconds=600), "accepted", 99
    )
    store, schedules, doses, access = Mock(), Mock(), Mock(), Mock()
    store.lock.return_value = now
    store.by_uuid.return_value = None
    store.latest.return_value = None
    store.create.return_value = record
    schedules.reminder_context.return_value = context
    doses.confirmed.return_value = False
    kwargs = dict(
        caller_id=caller,
        caller_is_admin=False,
        patient_id=patient,
        cmd=cmd,
        access=access,
        schedules=schedules,
        doses=doses,
        store=store,
    )
    return now, context, record, kwargs


def test_create_and_replay_before_dose_or_cooldown(setup):
    _, _, record, kwargs = setup
    result, created = send_reminder(None, **kwargs)
    assert created and result == record
    kwargs["store"].by_uuid.return_value = record
    kwargs["doses"].reset_mock()
    kwargs["cmd"] = replace(
        kwargs["cmd"],
        scheduled_at=kwargs["cmd"].scheduled_at.astimezone(
            __import__("datetime").timezone(timedelta(hours=7))
        ),
    )
    assert send_reminder(None, **kwargs) == (record, False)
    kwargs["doses"].confirmed.assert_not_called()


def test_pep_precedes_replay(setup):
    *_, kwargs = setup
    kwargs["access"].authorize_history.side_effect = Forbidden("khong_co_quyen")
    with pytest.raises(Forbidden):
        send_reminder(None, **kwargs)
    kwargs["store"].lock.assert_not_called()


def test_replay_payload_conflict(setup):
    _, _, record, kwargs = setup
    kwargs["store"].by_uuid.return_value = replace(record, schedule_id=999)
    with pytest.raises(Conflict, match="client_uuid_conflict"):
        send_reminder(None, **kwargs)


def test_cooldown_rounds_up_and_exact_boundary_allows(setup):
    now, _, record, kwargs = setup
    kwargs["store"].latest.return_value = replace(
        record, next_allowed_at=now + timedelta(microseconds=1)
    )
    with pytest.raises(TooManyRequests) as error:
        send_reminder(None, **kwargs)
    assert error.value.retry_after == 1
    kwargs["store"].latest.return_value = replace(record, next_allowed_at=now)
    assert send_reminder(None, **kwargs)[1]


@pytest.mark.parametrize(
    "delta", [timedelta(), timedelta(seconds=1), -timedelta(days=30, microseconds=1)]
)
def test_future_and_retention_boundaries(setup, delta):
    now, context, _, kwargs = setup
    with pytest.raises(DomainError):
        validate_occurrence(context, kwargs["patient_id"], now + delta, now, sending=True)


def test_exact_30_day_boundary_and_wrong_owner(setup):
    now, context, _, kwargs = setup
    at = now - timedelta(days=30)
    context.intake_time = time(9)
    validate_occurrence(context, kwargs["patient_id"], at, now, sending=True)
    with pytest.raises(Forbidden):
        validate_occurrence(context, uuid4(), at, now, sending=True)
    with pytest.raises(DomainError, match="invalid_dose_occurrence"):
        validate_occurrence(None, kwargs["patient_id"], at, now, sending=True)


def test_confirmed_stopped_and_self_send(setup):
    _, context, _, kwargs = setup
    kwargs["doses"].confirmed.return_value = True
    with pytest.raises(Conflict, match="dose_already_confirmed"):
        send_reminder(None, **kwargs)
    context.unavailable = True
    with pytest.raises(Conflict, match="dose_unavailable"):
        send_reminder(None, **kwargs)
    kwargs["caller_id"] = kwargs["patient_id"]
    with pytest.raises(Forbidden):
        send_reminder(None, **kwargs)


def test_received_owner_before_pep_and_content(setup):
    _, _, record, kwargs = setup
    store = kwargs["store"]
    store.received_metadata.return_value = []
    with pytest.raises(NotFound):
        received_detail(
            None,
            user_id=uuid4(),
            caller_is_admin=False,
            reminder_id=1,
            access=kwargs["access"],
            schedules=kwargs["schedules"],
            names=Mock(),
            store=store,
        )
    store.received_record.assert_not_called()
    kwargs["access"].authorize_history.assert_not_called()
    store.received_metadata.return_value = [(record.id, record.sender_user_id)]
    kwargs["access"].authorize_history.side_effect = Forbidden("khong_co_quyen")
    with pytest.raises(Forbidden):
        received_detail(
            None,
            user_id=record.patient_id,
            caller_is_admin=False,
            reminder_id=1,
            access=kwargs["access"],
            schedules=kwargs["schedules"],
            names=Mock(),
            store=store,
        )
    store.received_record.assert_not_called()


def test_received_filters_revoked_before_count(setup):
    _, _, record, kwargs = setup
    store, access = kwargs["store"], kwargs["access"]
    store.received_metadata.return_value = [(1, record.sender_user_id)]
    access.authorize_history.side_effect = [None, Forbidden("khong_co_quyen")]
    store.received_records.return_value = []
    assert received_list(
        None,
        user_id=record.patient_id,
        caller_is_admin=False,
        is_read=None,
        limit=20,
        offset=0,
        access=access,
        schedules=kwargs["schedules"],
        names=Mock(),
        store=store,
    ) == ([], 0, 0)
    store.received_records.assert_called_once_with(None, record.patient_id, [])
