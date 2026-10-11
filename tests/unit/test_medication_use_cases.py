from datetime import UTC, datetime, time, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from drugtime.modules.medication.application.create_medication import create_medication
from drugtime.modules.medication.application.delete_medication import delete_medication
from drugtime.modules.medication.application.get_medication import get_medication
from drugtime.modules.medication.application.list_medications import list_medications
from drugtime.modules.medication.application.update_medication import update_medication
from drugtime.modules.medication.domain.schedule_changes import ClosedSchedule, NewSchedule
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
PAST = LOCKED_AT - timedelta(days=3)
STOPPED_AT = LOCKED_AT - timedelta(hours=1)


class Recorded:
    """Port RecordedDoses giả: liều đã ghi với giờ dự kiến >= at, theo id lịch."""

    def __init__(self, calls, latest=None):
        self.calls, self.latest = calls, latest or {}

    def latest_at_or_after(self, uow, schedule_ids, at):
        self.calls.append(("latest_at_or_after", tuple(schedule_ids), at))
        return {i: t for i, t in self.latest.items() if i in schedule_ids}


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
    def __init__(
        self,
        calls,
        existing=None,
        owner=PATIENT,
        insert_result=7,
        stopped=False,
        deleted=False,
        mode=DosingMode.SCHEDULED,
        ids=(9, 4),
        reopened=2,
    ):
        self.calls, self.existing, self.owner = calls, existing, owner
        self.insert_result, self.stopped, self.deleted = insert_result, stopped, deleted
        self.mode, self.ids, self.reopened = mode, list(ids), reopened
        self.marked = {}  # id lịch -> stopped_at đã ghi khi đóng (dấu đóng do ngừng)

    def ids_of(self, uow, user_id):
        self.calls.append(("ids_of", user_id))
        return self.ids

    def mark_deleted(self, uow, i, at):
        self.calls.append(("mark_deleted", i, at))

    def closed_by_stop(self, uow, i, stopped_at):
        """`reopened` lịch mang dấu của lần ngừng tại stopped_at, giờ 08:00, 20:00…"""
        self.calls.append(("closed_by_stop", i, stopped_at))
        return tuple(
            ClosedSchedule(10 + k, time(8 + 12 * k), (1, 2), True, PAST, stopped_at)
            for k in range(self.reopened)
        )

    def resume(self, uow, i):
        self.calls.append(("resume", i))

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
        open_schedules = (
            (ScheduleView(1, time(8), (1, 2), False, PAST),)
            if self.mode is DosingMode.SCHEDULED and not self.stopped
            else ()
        )
        state = MedicationState(
            self.mode,
            self.stopped,
            (1, 2) if open_schedules else None,
            deleted=self.deleted,
            open_schedules=open_schedules,
            ended_at=STOPPED_AT if self.stopped else None,
        )
        return state, LOCKED_AT

    def close_schedule(self, uow, schedule_id, ended_at, stopped_at=None):
        self.calls.append(("close_schedule", schedule_id, ended_at))
        if stopped_at is not None:
            self.marked[schedule_id] = stopped_at

    def add_schedules(self, uow, i, schedules):
        self.calls.append(("add_schedules", i, tuple(schedules)))

    def patient_schedules(self, uow, patient_id, after_id, limit):
        self.calls.append(("patient_schedules", patient_id, after_id, limit))
        return []

    def update_fields(self, uow, i, fields):
        self.calls.append(("update_fields", i, fields))

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
    "close_schedule",
    "add_schedules",
    "stop",
    "mark_deleted",
    "resume",
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
        recorded=ports.get("recorded", Recorded(calls)),
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
        calls, bad, meds=Meds(calls, existing=(5, False)), catalog=FakeCatalog(calls, info=INFO)
    )
    assert not created and view.record.id == 5
    assert calls.names() == ["authorize_write", "find_by_client_uuid", "read", "catalog"]


def test_create_race_returns_row_of_winner():
    calls = Calls()

    class RacingMeds(Meds):
        def find_by_client_uuid(self, uow, user_id, client_uuid):
            super().find_by_client_uuid(uow, user_id, client_uuid)
            return None if self.calls.names().count("find_by_client_uuid") == 1 else (9, False)

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
    update(calls, MedicationChanges(frozenset({"intake_times"}), intake_times=(time(7),)))
    names = calls.names()
    assert names[:3] == ["owner_of", "authorize_write", "lock"]
    assert (
        names.index("latest_at_or_after")
        < names.index("close_schedule")
        < names.index("add_schedules")
    )
    assert ("update_fields", 7, {"doses_per_day": 1}) in calls
    # Lỗi B1: lịch cũ đóng và lịch mới mở đúng tại mốc lấy sau khi khóa, không phải now().
    assert ("close_schedule", 1, LOCKED_AT) in calls
    assert ("add_schedules", 7, (NewSchedule(time(7), (1, 2), True, LOCKED_AT),)) in calls


def test_update_times_keep_reminder_of_existing_time__AC10():
    calls = Calls()
    update(
        calls,
        MedicationChanges(frozenset({"intake_times"}), intake_times=(time(8), time(9))),
    )
    added = next(c for c in calls if c[0] == "add_schedules")[2]
    assert [(s.intake_time, s.reminder_enabled) for s in added] == [
        (time(8), False),
        (time(9), True),
    ]


def test_update_times_after_early_dose_shifts_boundaries__AC20():
    calls = Calls()
    early = LOCKED_AT + timedelta(minutes=10)
    update(
        calls,
        MedicationChanges(frozenset({"days_of_week"}), days_of_week=(3,)),
        recorded=Recorded(calls, {1: early}),
    )
    end = early + timedelta(seconds=1)
    assert ("close_schedule", 1, end) in calls
    assert ("add_schedules", 7, (NewSchedule(time(8), (3,), False, end),)) in calls


def test_update_without_schedule_change_does_not_read_doses():
    calls = Calls()
    update(calls, MedicationChanges(frozenset({"quantity_per_dose"}), quantity_per_dose=Decimal(2)))
    assert "latest_at_or_after" not in calls.names()


def test_update_stop_and_repeat_stop():
    calls = Calls()
    update(calls, MedicationChanges(frozenset({"stopped"}), stopped=True))
    assert ("close_schedule", 1, LOCKED_AT) in calls and ("stop", 7, LOCKED_AT) in calls
    calls = Calls()
    update(
        calls,
        MedicationChanges(frozenset({"stopped"}), stopped=True),
        meds=Meds(calls, stopped=True),
    )
    assert not WRITES & set(calls.names())


# --- Gửi lại client_uuid của thuốc đã xoá (contract Q3) --------------------------


def test_create_replay_of_deleted_404_creates_nothing():
    calls = Calls()
    with pytest.raises(NotFound, match="^user_medication_not_found$"):
        create(calls, meds=Meds(calls, existing=(5, True)))
    assert calls.names() == ["authorize_write", "find_by_client_uuid"]


def test_create_race_winner_deleted_404():
    calls = Calls()

    class RacingMeds(Meds):
        def find_by_client_uuid(self, uow, user_id, client_uuid):
            super().find_by_client_uuid(uow, user_id, client_uuid)
            return None if self.calls.names().count("find_by_client_uuid") == 1 else (9, True)

    with pytest.raises(NotFound):
        create(calls, meds=RacingMeds(calls, insert_result=None))
    assert "insert_schedules" not in calls.names()


# --- Danh sách -------------------------------------------------------------------


def lst(calls, caller=PATIENT, **ports):
    return list_medications(
        None,
        caller_id=caller,
        caller_is_admin=False,
        access=ports.get("access", Guard(calls)),
        catalog=ports.get("catalog", FakeCatalog(calls)),
        meds=ports.get("meds", Meds(calls)),
    )


def test_list_authorizes_self_read_before_reading():
    calls = Calls()
    lst(calls)
    assert calls[0] == ("authorize_read", PATIENT, PATIENT)
    assert calls[1] == ("ids_of", PATIENT)


def test_list_returns_views_in_port_order():
    calls = Calls()
    views = lst(calls, meds=Meds(calls, ids=(9, 4, 2)))
    assert [v.record.id for v in views] == [9, 4, 2]


def test_list_empty():
    calls = Calls()
    assert lst(calls, meds=Meds(calls, ids=())) == []


def test_list_forbidden_reads_nothing():
    calls = Calls()
    with pytest.raises(Forbidden):
        lst(calls, access=Guard(calls, allow_read=False))
    assert calls.names() == ["authorize_read"]


# --- Xoá -------------------------------------------------------------------------


def delete(calls, caller=PATIENT, **ports):
    return delete_medication(
        None,
        caller_id=caller,
        caller_is_admin=False,
        user_medication_id=7,
        access=ports.get("access", Guard(calls)),
        meds=ports.get("meds", Meds(calls)),
        recorded=ports.get("recorded", Recorded(calls)),
    )


def test_delete_unknown_or_deleted_404_before_authorize():
    calls = Calls()
    with pytest.raises(NotFound, match="^user_medication_not_found$"):
        delete(calls, meds=Meds(calls, owner=None))
    assert calls.names() == ["owner_of"]


def test_delete_forbidden_writes_nothing():
    calls = Calls()
    with pytest.raises(Forbidden):
        delete(calls, caller=OTHER, access=Guard(calls, allow_write=False))
    assert calls.names() == ["owner_of", "authorize_write"]
    assert calls[1] == ("authorize_write", OTHER, PATIENT)


def test_delete_closes_stops_marks_with_same_at():
    calls = Calls()
    delete(calls)
    assert calls == [
        ("owner_of", 7),
        ("authorize_write", PATIENT, PATIENT),
        ("lock", 7),
        ("latest_at_or_after", (1,), LOCKED_AT),
        ("close_schedule", 1, LOCKED_AT),
        ("stop", 7, LOCKED_AT),
        ("mark_deleted", 7, LOCKED_AT),
    ]


def test_delete_after_early_dose_closes_after_dose__AC24():
    calls = Calls()
    early = LOCKED_AT + timedelta(minutes=10)
    delete(calls, recorded=Recorded(calls, {1: early}))
    assert ("close_schedule", 1, early + timedelta(seconds=1)) in calls
    assert ("stop", 7, LOCKED_AT) in calls and ("mark_deleted", 7, LOCKED_AT) in calls


def test_delete_race_deleted_after_lock_404():
    calls = Calls()
    with pytest.raises(NotFound):
        delete(calls, meds=Meds(calls, deleted=True))
    assert not WRITES & set(calls.names())


# --- Sửa sau khi xoá, dùng lại ----------------------------------------------------

UNSTOP = MedicationChanges(frozenset({"stopped"}), stopped=False)


def test_update_deleted_after_lock_404():
    calls = Calls()
    with pytest.raises(NotFound):
        update(
            calls,
            MedicationChanges(frozenset({"quantity_per_dose"}), quantity_per_dose=Decimal("2")),
            meds=Meds(calls, deleted=True),
        )
    assert not WRITES & set(calls.names())


def test_reactivate_scheduled_reopens_at_lock_time():
    calls = Calls()
    update(calls, UNSTOP, meds=Meds(calls, stopped=True))
    assert ("closed_by_stop", 7, STOPPED_AT) in calls
    assert "latest_at_or_after" not in calls.names()
    added = next(c for c in calls if c[0] == "add_schedules")
    assert added[2] == (
        NewSchedule(time(8), (1, 2), True, LOCKED_AT),
        NewSchedule(time(20), (1, 2), True, LOCKED_AT),
    )
    assert WRITES & set(calls.names()) == {"add_schedules", "update_fields", "resume"}
    assert calls.names().index("add_schedules") < calls.names().index("resume")


def test_stop_after_early_dose_closes_after_dose__AC24():
    calls = Calls()
    early = LOCKED_AT + timedelta(minutes=10)
    update(
        calls,
        MedicationChanges(frozenset({"stopped"}), stopped=True),
        recorded=Recorded(calls, {1: early}),
    )
    assert ("close_schedule", 1, early + timedelta(seconds=1)) in calls
    assert ("stop", 7, LOCKED_AT) in calls


def test_switch_to_as_needed_after_early_dose_closes_after_dose__AC24():
    calls = Calls()
    early = LOCKED_AT + timedelta(minutes=10)
    update(
        calls,
        MedicationChanges(
            frozenset({"dosing_mode", "max_doses_per_day"}),
            dosing_mode=DosingMode.AS_NEEDED,
            max_doses_per_day=2,
        ),
        recorded=Recorded(calls, {1: early}),
    )
    assert ("close_schedule", 1, early + timedelta(seconds=1)) in calls
    assert "add_schedules" not in calls.names()


def test_reactivate_scheduled_zero_schedules_violation():
    calls = Calls()
    with pytest.raises(DomainError, match="^medication_rule_violation$"):
        update(calls, UNSTOP, meds=Meds(calls, stopped=True, reopened=0))


def test_reactivate_as_needed_ok_without_schedules():
    calls = Calls()
    update(calls, UNSTOP, meds=Meds(calls, stopped=True, mode=DosingMode.AS_NEEDED, reopened=0))
    assert ("resume", 7) in calls
    assert "add_schedules" not in calls.names()


def test_reactivate_as_needed_never_reopens_schedules__R2():
    """Lịch theo giờ cũ vừa đóng sau liều sớm không được mở lại cho thuốc khi cần."""
    calls = Calls()
    update(calls, UNSTOP, meds=Meds(calls, stopped=True, mode=DosingMode.AS_NEEDED, reopened=2))
    assert WRITES & set(calls.names()) == {"resume"}
    assert "closed_by_stop" not in calls.names()


class FutureMeds(Meds):
    """Thuốc có thêm lịch 22:00 bắt đầu ở tương lai (sau một lần thay lịch sau liều sớm)."""

    def lock(self, uow, i):
        state, at = super().lock(uow, i)
        future = ScheduleView(2, time(22), (1, 2), True, LOCKED_AT + timedelta(minutes=20))
        return (
            MedicationState(
                state.dosing_mode,
                state.stopped,
                state.open_days_of_week,
                deleted=state.deleted,
                open_schedules=(*state.open_schedules, future),
                ended_at=state.ended_at,
            ),
            at,
        )


STOP = MedicationChanges(frozenset({"stopped"}), stopped=True)


def test_stop_marks_every_open_schedule_including_future__AC28():
    calls = Calls()
    meds = FutureMeds(calls)
    update(calls, STOP, meds=meds)
    assert meds.marked == {1: LOCKED_AT, 2: LOCKED_AT}
    assert ("close_schedule", 2, LOCKED_AT + timedelta(minutes=20)) in calls
    assert ("stop", 7, LOCKED_AT) in calls


def test_switch_to_as_needed_does_not_mark():
    calls = Calls()
    meds = FutureMeds(calls)
    update(
        calls,
        MedicationChanges(
            frozenset({"dosing_mode", "max_doses_per_day"}),
            dosing_mode=DosingMode.AS_NEEDED,
            max_doses_per_day=2,
        ),
        meds=meds,
    )
    assert "close_schedule" in calls.names() and meds.marked == {}


def test_replace_times_does_not_mark():
    calls = Calls()
    meds = Meds(calls)
    update(
        calls,
        MedicationChanges(frozenset({"intake_times"}), intake_times=(time(7), time(22))),
        meds=meds,
    )
    assert "close_schedule" in calls.names() and meds.marked == {}


def test_delete_marks_schedules():
    calls = Calls()
    meds = FutureMeds(calls)
    delete(calls, meds=meds)
    assert meds.marked == {1: LOCKED_AT, 2: LOCKED_AT}


def test_reactivate_opens_marked_and_sets_doses_per_day__AC27_M3():
    calls = Calls()
    update(calls, UNSTOP, meds=Meds(calls, stopped=True))
    added = next(c for c in calls if c[0] == "add_schedules")
    assert [s.intake_time for s in added[2]] == [time(8), time(20)]
    assert ("update_fields", 7, {"doses_per_day": 2}) in calls
    assert calls.names().index("update_fields") < calls.names().index("resume")


class DuplicateMarkedMeds(Meds):
    def closed_by_stop(self, uow, i, stopped_at):
        self.calls.append(("closed_by_stop", i, stopped_at))
        return (
            ClosedSchedule(10, time(8), (1, 2), True, PAST, stopped_at),
            ClosedSchedule(11, time(8), (1, 2), False, PAST, stopped_at),
        )


def test_reactivate_counts_one_schedule_per_time__M3():
    calls = Calls()
    update(calls, UNSTOP, meds=DuplicateMarkedMeds(calls, stopped=True))
    added = next(c for c in calls if c[0] == "add_schedules")
    assert [(s.intake_time, s.reminder_enabled) for s in added[2]] == [(time(8), False)]
    assert ("update_fields", 7, {"doses_per_day": 1}) in calls


def test_unstop_active_is_noop():
    calls = Calls()
    update(calls, UNSTOP)
    assert not WRITES & set(calls.names())


def test_reactivate_denied_writes_nothing():
    calls = Calls()
    with pytest.raises(Forbidden):
        update(
            calls,
            UNSTOP,
            caller=OTHER,
            access=Guard(calls, allow_write=False),
            meds=Meds(calls, stopped=True),
        )
    assert calls.names() == ["owner_of", "authorize_write"]
