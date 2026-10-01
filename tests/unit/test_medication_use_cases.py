from datetime import UTC, datetime, time
from decimal import Decimal
from uuid import uuid4

import pytest

from drugtime.modules.medication.application.create_medication import create_medication
from drugtime.modules.medication.application.get_medication import get_medication
from drugtime.modules.medication.application.update_medication import update_medication
from drugtime.modules.medication.domain.user_medication import (
    DosingMode,
    MedicationChanges,
    MedicationInfo,
    MedicationState,
    NewMedication,
    ScheduleView,
    UserMedicationRecord,
)
from drugtime.shared.errors import DomainError, Forbidden, NotFound

PATIENT, OTHER = uuid4(), uuid4()
INFO = MedicationInfo(1, "Amlodipin 5mg", "5 mg", "Viên nén", True)
LOCKED_AT = datetime(2026, 10, 1, 2, 0, tzinfo=UTC)


class Calls(list):
    def names(self):
        return [c[0] for c in self]


class Guard:
    def __init__(self, calls, allow_read=True, allow_write=True):
        self.calls, self.allow_read, self.allow_write = calls, allow_read, allow_write

    def authorize_read(self, uow, caller_id, caller_is_admin, patient_id):
        self.calls.append(("authorize_read", caller_id, patient_id))
        if not self.allow_read:
            raise Forbidden("khong_co_quyen")

    def authorize_write(self, uow, caller_id, caller_is_admin, patient_id):
        self.calls.append(("authorize_write", caller_id, patient_id))
        if not self.allow_write:
            raise Forbidden("khong_co_quyen")


class FakeCatalog:
    def __init__(self, calls, info=INFO):
        self.calls, self.info = calls, info

    def get_medication(self, uow, medication_id, *, include_deleted=False):
        self.calls.append(("catalog", medication_id, include_deleted))
        return self.info


class Meds:
    def __init__(self, calls, existing=None, owner=PATIENT, insert_result=7, stopped=False):
        self.calls, self.existing, self.owner = calls, existing, owner
        self.insert_result, self.stopped = insert_result, stopped

    def owner_of(self, uow, i):
        self.calls.append(("owner_of", i))
        return self.owner

    def find_by_client_uuid(self, uow, user_id, client_uuid):
        self.calls.append(("find_by_client_uuid", user_id))
        return self.existing

    def default_prescription(self, uow, user_id):
        self.calls.append(("default_prescription", user_id))
        return 3

    def insert(self, uow, user_id, prescription_id, cmd, has_interaction_data):
        self.calls.append(("insert", user_id, prescription_id, has_interaction_data))
        return self.insert_result

    def insert_schedules(self, uow, i, times, days, effective_from=None):
        self.calls.append(("insert_schedules", i, times, days))
        self.effective_from = effective_from

    def lock(self, uow, i):
        self.calls.append(("lock", i))
        return MedicationState(DosingMode.SCHEDULED, self.stopped, (1, 2)), LOCKED_AT

    def update_fields(self, uow, i, fields):
        self.calls.append(("update_fields", i, fields))

    def close_open_schedules(self, uow, i, at):
        self.calls.append(("close_open_schedules", i, at))

    def stop(self, uow, i, at):
        self.calls.append(("stop", i, at))

    def read(self, uow, i):
        self.calls.append(("read", i))
        return UserMedicationRecord(
            id=i,
            user_id=self.owner or PATIENT,
            medication_id=1,
            dosing_mode=DosingMode.SCHEDULED,
            quantity_per_dose=Decimal("1"),
            doses_per_day=1,
            intake_timing=None,
            stock_quantity=None,
            has_interaction_data=True,
            ended_at=None,
            schedules=(ScheduleView(1, time(8), (1, 2), True, datetime.now(UTC)),),
        )


WRITES = {
    "default_prescription",
    "insert",
    "insert_schedules",
    "update_fields",
    "close_open_schedules",
    "stop",
}


def cmd(**kw):
    base = dict(
        client_uuid=uuid4(),
        medication_id=1,
        quantity_per_dose=Decimal("1"),
        dosing_mode=DosingMode.SCHEDULED,
        intake_times=(time(20), time(8)),
    )
    return NewMedication(**{**base, **kw})


def create(calls, c=None, caller=PATIENT, **ports):
    return create_medication(
        None,
        caller_id=caller,
        caller_is_admin=False,
        cmd=c or cmd(),
        access=ports.get("access", Guard(calls)),
        catalog=ports.get("catalog", FakeCatalog(calls)),
        meds=ports.get("meds", Meds(calls)),
    )


def update(calls, changes, caller=PATIENT, **ports):
    return update_medication(
        None,
        caller_id=caller,
        caller_is_admin=False,
        user_medication_id=7,
        changes=changes,
        access=ports.get("access", Guard(calls)),
        catalog=ports.get("catalog", FakeCatalog(calls)),
        meds=ports.get("meds", Meds(calls)),
    )


def test_create_checks_write_access_before_anything():
    calls = Calls()
    with pytest.raises(Forbidden):
        create(calls, access=Guard(calls, allow_write=False))
    assert calls.names() == ["authorize_write"]
    assert calls[0] == ("authorize_write", PATIENT, PATIENT)


def test_create_scheduled_writes_prescription_medication_and_schedules():
    calls = Calls()
    view, created = create(calls)
    assert created and view.record.id == 7 and view.medication == INFO
    assert calls.names() == [
        "authorize_write",
        "find_by_client_uuid",
        "catalog",
        "default_prescription",
        "insert",
        "insert_schedules",
        "read",
        "catalog",
    ]
    assert ("insert", PATIENT, 3, True) in calls
    assert ("insert_schedules", 7, (time(8), time(20)), (1, 2, 3, 4, 5, 6, 7)) in calls
    assert ("catalog", 1, False) in calls and ("catalog", 1, True) in calls


def test_create_as_needed_has_no_schedule():
    calls = Calls()
    create(calls, cmd(dosing_mode=DosingMode.AS_NEEDED, intake_times=None, max_doses_per_day=2))
    assert "insert_schedules" not in calls.names()


def test_create_replay_returns_existing_without_catalog_check():
    calls = Calls()
    # Body sai quy tắc và danh mục đã mất thuốc: lần gửi lại vẫn trả thuốc cũ.
    bad = cmd(intake_times=None)
    view, created = create(
        calls, bad, meds=Meds(calls, existing=5), catalog=FakeCatalog(calls, info=INFO)
    )
    assert not created and view.record.id == 5
    assert calls.names() == ["authorize_write", "find_by_client_uuid", "read", "catalog"]


def test_create_race_returns_row_of_winner():
    calls = Calls()

    class RacingMeds(Meds):
        def find_by_client_uuid(self, uow, user_id, client_uuid):
            super().find_by_client_uuid(uow, user_id, client_uuid)
            return None if self.calls.names().count("find_by_client_uuid") == 1 else 9

    view, created = create(calls, meds=RacingMeds(calls, insert_result=None))
    assert not created and view.record.id == 9
    assert "insert_schedules" not in calls.names()


def test_create_rule_violation_writes_nothing():
    calls = Calls()
    with pytest.raises(DomainError, match="medication_rule_violation"):
        create(calls, cmd(intake_times=None))
    assert not WRITES & set(calls.names())


def test_create_unknown_catalog_rejected():
    calls = Calls()
    with pytest.raises(DomainError, match="catalog_medication_not_found"):
        create(calls, catalog=FakeCatalog(calls, info=None))
    assert not WRITES & set(calls.names())


def test_get_unknown_id_404_before_authorize():
    calls = Calls()
    with pytest.raises(NotFound, match="user_medication_not_found"):
        get_medication(
            None,
            caller_id=OTHER,
            caller_is_admin=False,
            user_medication_id=7,
            access=Guard(calls),
            catalog=FakeCatalog(calls),
            meds=Meds(calls, owner=None),
        )
    assert calls.names() == ["owner_of"]


def test_get_authorizes_read_against_owner():
    calls = Calls()
    get_medication(
        None,
        caller_id=OTHER,
        caller_is_admin=False,
        user_medication_id=7,
        access=Guard(calls),
        catalog=FakeCatalog(calls),
        meds=Meds(calls),
    )
    assert calls[:2] == [("owner_of", 7), ("authorize_read", OTHER, PATIENT)]


def test_update_unknown_id_404_before_authorize():
    calls = Calls()
    with pytest.raises(NotFound):
        update(
            calls,
            MedicationChanges(frozenset({"stopped"}), stopped=True),
            meds=Meds(calls, owner=None),
        )
    assert calls.names() == ["owner_of"]


def test_update_denied_writes_nothing():
    calls = Calls()
    with pytest.raises(Forbidden):
        update(
            calls,
            MedicationChanges(frozenset({"stopped"}), stopped=True),
            caller=OTHER,
            access=Guard(calls, allow_write=False),
        )
    assert calls.names() == ["owner_of", "authorize_write"]
    assert calls[1] == ("authorize_write", OTHER, PATIENT)


def test_update_times_closes_then_inserts_with_kept_days():
    calls = Calls()
    meds = Meds(calls)
    update(
        calls, MedicationChanges(frozenset({"intake_times"}), intake_times=(time(7),)), meds=meds
    )
    names = calls.names()
    assert names[:3] == ["owner_of", "authorize_write", "lock"]
    assert names.index("close_open_schedules") < names.index("insert_schedules")
    assert ("insert_schedules", 7, (time(7),), (1, 2)) in calls
    assert ("update_fields", 7, {"doses_per_day": 1}) in calls
    # Lỗi B1: lịch cũ đóng và lịch mới mở đúng tại mốc lấy sau khi khóa, không phải now().
    assert ("close_open_schedules", 7, LOCKED_AT) in calls
    assert meds.effective_from == LOCKED_AT


def test_update_stop_and_repeat_stop():
    calls = Calls()
    update(calls, MedicationChanges(frozenset({"stopped"}), stopped=True))
    assert ("close_open_schedules", 7, LOCKED_AT) in calls and ("stop", 7, LOCKED_AT) in calls
    calls = Calls()
    update(
        calls,
        MedicationChanges(frozenset({"stopped"}), stopped=True),
        meds=Meds(calls, stopped=True),
    )
    assert not WRITES & set(calls.names())
