from datetime import UTC, datetime, time, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from drugtime.modules.medication.adapters.inbound import http
from drugtime.modules.medication.application.list_patient_schedules import list_patient_schedules
from drugtime.modules.medication.application.manage_schedules import (
    add_schedule,
    remove_schedule,
    update_schedule,
)
from drugtime.modules.medication.domain import schedule_cursor
from drugtime.modules.medication.domain.schedule_changes import NewSchedule
from drugtime.modules.medication.domain.user_medication import DosingMode, PatientScheduleRecord
from drugtime.shared.errors import DomainError, Forbidden, NotFound
from tests.unit.test_medication_use_cases import (
    LOCKED_AT,
    OTHER,
    PATIENT,
    WRITES,
    Calls,
    FakeCatalog,
    FutureMeds,
    Guard,
    Meds,
    Recorded,
)

OPS = {
    "add": lambda calls, **p: add_schedule(
        None,
        caller_id=p.get("caller", PATIENT),
        caller_is_admin=False,
        user_medication_id=7,
        intake_time=time(12),
        reminder_enabled=True,
        **_ports(calls, p),
    ),
    "update": lambda calls, **p: update_schedule(
        None,
        caller_id=p.get("caller", PATIENT),
        caller_is_admin=False,
        user_medication_id=7,
        schedule_id=1,
        intake_time=time(7),
        reminder_enabled=None,
        **_ports(calls, p),
    ),
    "remove": lambda calls, **p: remove_schedule(
        None,
        caller_id=p.get("caller", PATIENT),
        caller_is_admin=False,
        user_medication_id=7,
        schedule_id=1,
        **_ports(calls, p),
    ),
}


def _ports(calls, p):
    return {
        "access": p.get("access", Guard(calls)),
        "catalog": p.get("catalog", FakeCatalog(calls)),
        "meds": p.get("meds", Meds(calls)),
        "recorded": p.get("recorded", Recorded(calls)),
    }


@pytest.mark.parametrize("op", ["update", "remove"])
def test_schedule_writes_do_not_mark_closed_by_stop(op):
    calls = Calls()
    meds = FutureMeds(calls)
    OPS[op](calls, meds=meds)
    assert "close_schedule" in calls.names() and meds.marked == {}


@pytest.mark.parametrize("op", OPS)
def test_unknown_medication_404_before_authorize(op):
    calls = Calls()
    with pytest.raises(NotFound, match="^user_medication_not_found$"):
        OPS[op](calls, meds=Meds(calls, owner=None))
    assert calls.names() == ["owner_of"]


@pytest.mark.parametrize("op", OPS)
def test_denied_writes_nothing__AC15(op):
    calls = Calls()
    with pytest.raises(Forbidden):
        OPS[op](calls, caller=OTHER, access=Guard(calls, allow_write=False))
    assert calls.names() == ["owner_of", "authorize_write"]
    assert calls[1] == ("authorize_write", OTHER, PATIENT)


@pytest.mark.parametrize("op", OPS)
def test_deleted_after_lock_404(op):
    calls = Calls()
    with pytest.raises(NotFound, match="^user_medication_not_found$"):
        OPS[op](calls, meds=Meds(calls, deleted=True))
    assert not WRITES & set(calls.names())


@pytest.mark.parametrize("op", OPS)
def test_stopped_medication_422_writes_nothing(op):
    calls = Calls()
    with pytest.raises(DomainError, match="^medication_stopped$"):
        OPS[op](calls, meds=Meds(calls, stopped=True))
    assert not WRITES & set(calls.names())


def test_add_sets_doses_and_inserts_at_lock_time__AC1():
    calls = Calls()
    view = OPS["add"](calls)
    assert view.record.id == 7
    assert ("add_schedules", 7, (NewSchedule(time(12), (1, 2), True, LOCKED_AT),)) in calls
    assert ("update_fields", 7, {"doses_per_day": 2}) in calls
    assert "close_schedule" not in calls.names()


def test_update_closes_then_inserts_at_close_time__AC3():
    calls = Calls()
    OPS["update"](calls)
    names = calls.names()
    assert names[:4] == ["owner_of", "authorize_write", "lock", "latest_at_or_after"]
    assert names.index("close_schedule") < names.index("add_schedules")
    assert ("close_schedule", 1, LOCKED_AT) in calls
    # giữ ngày và trạng thái nhắc (tắt) của lịch cũ
    assert ("add_schedules", 7, (NewSchedule(time(7), (1, 2), False, LOCKED_AT),)) in calls
    assert "update_fields" not in names


def test_update_after_early_dose_starts_after_it__AC20():
    calls = Calls()
    early = LOCKED_AT + timedelta(minutes=10)
    OPS["update"](calls, recorded=Recorded(calls, {1: early}))
    end = early + timedelta(seconds=1)
    assert ("close_schedule", 1, end) in calls
    assert ("add_schedules", 7, (NewSchedule(time(7), (1, 2), False, end),)) in calls


def test_remove_last_schedule_422_writes_nothing__AC8():
    calls = Calls()
    with pytest.raises(DomainError, match="^last_schedule_not_removable$"):
        OPS["remove"](calls)
    assert not WRITES & set(calls.names())


def test_add_as_needed_422():
    calls = Calls()
    with pytest.raises(DomainError, match="^medication_rule_violation$"):
        OPS["add"](calls, meds=Meds(calls, mode=DosingMode.AS_NEEDED))


def test_write_without_configured_recorded_doses_fails(monkeypatch):
    monkeypatch.setattr(http, "_recorded_doses", None)
    with pytest.raises(RuntimeError, match="configure"):
        http.recorded_doses()


# --- list_patient_schedules -------------------------------------------------


def _record(i, medication_id=1, ended_at=None):
    return PatientScheduleRecord(
        id=i,
        user_medication_id=7,
        medication_id=medication_id,
        quantity_per_dose=Decimal("1"),
        doses_per_day=2,
        intake_timing=None,
        intake_time=time(8),
        days_of_week=(1, 2),
        reminder_enabled=True,
        effective_from=datetime(2026, 10, 1, tzinfo=UTC),
        ended_at=ended_at,
    )


class PageMeds(Meds):
    def __init__(self, calls, rows):
        super().__init__(calls)
        self.rows = rows

    def patient_schedules(self, uow, patient_id, after_id, limit):
        self.calls.append(("patient_schedules", patient_id, after_id, limit))
        return [r for r in self.rows if r.id > after_id][:limit]


def lst(calls, rows=(), caller=PATIENT, limit=100, cursor=None, **ports):
    return list_patient_schedules(
        None,
        caller_id=caller,
        caller_is_admin=False,
        patient_id=PATIENT,
        limit=limit,
        cursor=cursor,
        access=ports.get("access", Guard(calls)),
        catalog=ports.get("catalog", FakeCatalog(calls)),
        meds=ports.get("meds", PageMeds(calls, list(rows))),
    )


def test_list_authorizes_before_reading__AC12():
    calls = Calls()
    lst(calls, [_record(3)], caller=OTHER)
    assert calls.names()[0] == "authorize_read"
    assert calls[0] == ("authorize_read", OTHER, PATIENT)


def test_list_forbidden_reads_nothing_even_with_bad_cursor__AC13():
    calls = Calls()
    with pytest.raises(Forbidden):
        lst(calls, cursor="rác", access=Guard(calls, allow_read=False))
    assert calls.names() == ["authorize_read"]


def test_list_pages_and_last_page_has_no_cursor__AC23():
    rows = [_record(i) for i in (3, 5, 8, 9, 12)]
    calls = Calls()
    seen, cursor, pages = [], None, 0
    while True:
        page = lst(calls, rows, limit=2, cursor=cursor)
        pages += 1
        seen += [v.record.id for v in page.items]
        cursor = page.next_cursor
        if cursor is None:
            break
    assert (pages, seen) == (3, [3, 5, 8, 9, 12])
    assert ("patient_schedules", PATIENT, 0, 3) in calls  # lấy dư một dòng


def test_list_exact_page_size_has_no_cursor():
    calls = Calls()
    page = lst(calls, [_record(1), _record(2)], limit=2)
    assert page.next_cursor is None and len(page.items) == 2


def test_list_cursor_of_other_patient_invalid():
    calls = Calls()
    with pytest.raises(DomainError, match="^invalid_cursor$"):
        lst(calls, cursor=schedule_cursor.encode(uuid4(), 3))


def test_list_maps_catalog_once_per_medication():
    calls = Calls()
    page = lst(calls, [_record(1, 1), _record(2, 1), _record(3, 2)])
    assert [c for c in calls if c[0] == "catalog"] == [("catalog", 1, True), ("catalog", 2, True)]
    assert len(page.items) == 3


def test_list_empty():
    calls = Calls()
    page = lst(calls)
    assert page.items == [] and page.next_cursor is None
