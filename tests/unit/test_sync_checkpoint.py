"""Task 3.19 (P12): use case checkpoint đồng bộ chạy PEP (ghi, chính chủ) trước khi ghi."""

from uuid import uuid4

import pytest

from drugtime.modules.adherence.adapters.outbound import other_modules
from drugtime.modules.adherence.application.record_sync_checkpoint import record_sync_checkpoint
from drugtime.shared.errors import Forbidden


class Access:
    def __init__(self, events, error=None):
        self.events, self.error = events, error

    def authorize_sync_checkpoint(self, uow, caller_id, caller_is_admin):
        self.events.append(("authorize", caller_id, caller_is_admin))
        if self.error:
            raise self.error


class Checkpoints:
    def __init__(self, events):
        self.events = events

    def record(self, uow, user_id):
        self.events.append(("record", user_id))


def test_authorizes_write_before_recording__AC13():
    events, caller = [], uuid4()

    record_sync_checkpoint(
        None,
        caller_id=caller,
        caller_is_admin=False,
        access=Access(events),
        checkpoints=Checkpoints(events),
    )

    assert events == [("authorize", caller, False), ("record", caller)]


@pytest.mark.parametrize("reason", ["consent_revoked", "khong_co_quyen"])
def test_forbidden_does_not_record__AC13(reason):
    events, caller = [], uuid4()

    with pytest.raises(Forbidden, match=reason):
        record_sync_checkpoint(
            None,
            caller_id=caller,
            caller_is_admin=reason == "khong_co_quyen",
            access=Access(events, Forbidden(reason)),
            checkpoints=Checkpoints(events),
        )

    assert [e[0] for e in events] == ["authorize"]


def test_adapter_uses_pep_write_on_callers_own_adherence(monkeypatch):
    calls, caller = [], uuid4()
    monkeypatch.setattr(other_modules.access, "authorize", lambda uow, **kw: calls.append(kw))

    other_modules.AccessGuardAdapter().authorize_sync_checkpoint(None, caller, False)

    assert calls == [
        dict(
            caller_id=caller,
            caller_is_admin=False,
            patient_id=caller,
            scope=other_modules.access.Scope.ADHERENCE,
            action=other_modules.access.Action.WRITE,
        )
    ]


def test_dose_batch_authorization_is_write__Q2(monkeypatch):
    calls, caller, patient = [], uuid4(), uuid4()
    monkeypatch.setattr(other_modules.access, "authorize", lambda uow, **kw: calls.append(kw))

    other_modules.AccessGuardAdapter().authorize_dose_write(None, caller, False, patient)

    assert calls[0]["action"] is other_modules.access.Action.WRITE
    assert calls[0]["patient_id"] == patient


def test_notification_access_stays_read__regression(monkeypatch):
    # Hộp thư cảnh báo của người thân kiểm quyền qua authorize_adherence: phải là quyền đọc.
    calls, caller, patient = [], uuid4(), uuid4()
    monkeypatch.setattr(other_modules.access, "authorize", lambda uow, **kw: calls.append(kw))

    other_modules.AccessGuardAdapter().authorize_adherence(None, caller, False, patient)

    assert calls[0].get("action", other_modules.access.Action.READ) is (
        other_modules.access.Action.READ
    )
    assert calls[0]["patient_id"] == patient


def test_erase_user_removes_pending_and_checkpoint_before_dose_logs__AC16():
    from unittest.mock import Mock

    from drugtime.modules.adherence.application.erase_user import erase_user

    user, events = uuid4(), Mock()
    events.schedules.ids_of.return_value = [3, 4]

    erase_user(
        None,
        user,
        schedules=events.schedules,
        dose_logs=events.dose_logs,
        notifications=events.notifications,
        checkpoints=events.checkpoints,
        pending=events.pending,
    )

    names = [c[0] for c in events.mock_calls]
    assert names == [
        "pending.erase_for_patient",
        "checkpoints.erase_for_user",
        "schedules.ids_of",
        "dose_logs.erase_for_schedules",
        "notifications.erase_for_user",
    ]
    events.pending.erase_for_patient.assert_called_once_with(None, user)
    events.checkpoints.erase_for_user.assert_called_once_with(None, user)
