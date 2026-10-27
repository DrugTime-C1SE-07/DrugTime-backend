"""Task 3.19: medication.occurrences_between trên Postgres thật, chạy bằng worker_role."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from test_adherence_history_api import VN, all_doses
from test_adherence_history_api import history_data as history_data
from test_missed_dose_verification import World

from drugtime.modules.medication.api import occurrences_between
from drugtime.shared.db import SqlUnitOfWork

OCT5 = datetime(2026, 10, 5, tzinfo=VN)


def occurrences(role_engines, patient, start, end):
    with role_engines["worker_role"].begin() as connection:
        found = occurrences_between(SqlUnitOfWork(connection), start, end)
    return [(o.schedule_id, o.scheduled_at) for o in found if o.patient_id == patient]


@pytest.fixture
def data(history_data):
    return history_data


def test_daily_one_occurrence__AC1(data, role_engines):
    occ = data.schedule(OCT5 + timedelta(hours=8))
    start, end = datetime(2026, 10, 5, 0, tzinfo=UTC), datetime(2026, 10, 5, 2, tzinfo=UTC)
    with role_engines["worker_role"].begin() as connection:
        found = [
            o
            for o in occurrences_between(SqlUnitOfWork(connection), start, end)
            if o.patient_id == data.patient
        ]
    assert len(found) == 1
    assert isinstance(found[0].schedule_id, int) and found[0].schedule_id == occ.schedule_id
    assert found[0].scheduled_at == datetime(2026, 10, 5, 1, tzinfo=UTC)


def test_schedule_replaced_same_time__AC4(data, role_engines):
    switch = OCT5 + timedelta(hours=7, minutes=45)
    entry = data.medication()
    old = data.schedule(
        OCT5 + timedelta(hours=8),
        medication=entry,
        effective=OCT5 - timedelta(days=1),
        ended=switch,
    )
    new = data.schedule(OCT5 + timedelta(hours=8), medication=entry, effective=switch)
    found = occurrences(
        role_engines, data.patient, OCT5 - timedelta(days=1), OCT5 + timedelta(days=1)
    )
    assert found == [
        (old.schedule_id, OCT5 - timedelta(days=1) + timedelta(hours=8)),
        (new.schedule_id, OCT5 + timedelta(hours=8)),
    ]


def test_matches_history_generation__AC10(data, role_engines):
    day = OCT5
    data.schedule(day + timedelta(hours=8))  # lịch mở
    data.schedule(day + timedelta(hours=9), ended=day + timedelta(hours=12))  # đóng trong ngày
    data.schedule(day + timedelta(hours=10), ended=day + timedelta(hours=9))  # đóng trước giờ
    deleted = data.schedule(day + timedelta(hours=11))
    data.db.execute(
        text("UPDATE user_medications SET ended_at = :t, deleted_at = :t WHERE id = :u"),
        {"t": day + timedelta(hours=13), "u": deleted.user_medication_id},
    )
    data.schedule(day + timedelta(hours=23, minutes=30))
    data.now = day + timedelta(days=1, hours=6)
    response = data.read(**{"from": day.date().isoformat(), "to": day.date().isoformat()})
    assert response.status_code == 200
    history = {
        (d["schedule_id"], datetime.fromisoformat(d["scheduled_at"]))
        for d in all_doses(response.json())
    }
    worker = set(occurrences(role_engines, data.patient, day, day + timedelta(days=1)))
    assert worker == history and len(worker) == 4


def test_prefilter_keeps_results__AC11(data, role_engines):
    times = [(7, 0), (8, 0), (9, 0), (23, 55), (0, 5)]
    occs = {hm: data.schedule(OCT5 + timedelta(hours=hm[0], minutes=hm[1])) for hm in times}
    narrow = occurrences(
        role_engines,
        data.patient,
        OCT5 + timedelta(hours=7, minutes=30),
        OCT5 + timedelta(hours=8, minutes=1),
    )
    assert narrow == [(occs[(8, 0)].schedule_id, OCT5 + timedelta(hours=8))]
    midnight = occurrences(
        role_engines,
        data.patient,
        OCT5 + timedelta(hours=23, minutes=50),
        OCT5 + timedelta(days=1, minutes=10),
    )
    assert midnight == [
        (occs[(23, 55)].schedule_id, OCT5 + timedelta(hours=23, minutes=55)),
        (occs[(0, 5)].schedule_id, OCT5 + timedelta(days=1, minutes=5)),
    ]
    whole = occurrences(role_engines, data.patient, OCT5, OCT5 + timedelta(days=1, hours=1))
    assert len(whole) == len(times) + 1  # 00:05 của ngày sau cũng nằm trong cửa sổ ≥ 24 giờ
    assert set(narrow + midnight) <= set(whole)


@pytest.mark.parametrize("toggle_hour,considered", [(9, True), (7, False)])
def test_reminder_disabled_and_toggle_time__AC12(data, role_engines, toggle_hour, considered):
    w = World(data, role_engines["worker_role"])
    family = w.make.family_of(w.patient)
    family_token, patient_token = w.token(family), w.token(w.patient)
    at = OCT5 + timedelta(hours=8)
    entry = data.medication()
    toggle = OCT5 + timedelta(hours=toggle_hour)
    old = data.schedule(at, medication=entry, ended=toggle)
    data.schedule(at, medication=entry, effective=toggle, reminder=False)
    off = data.schedule(at + timedelta(minutes=5), reminder=False)  # tắt nhắc từ đầu
    found = occurrences(role_engines, data.patient, OCT5, OCT5 + timedelta(days=1))
    assert found == ([(old.schedule_id, at)] if considered else [])
    w.checkpoint(at + timedelta(hours=3))
    w.run(at + timedelta(hours=2, minutes=10))
    logs = w.logs()
    assert [r["schedule_id"] for r in logs] == ([old.schedule_id] if considered else [])
    assert all(r["schedule_id"] != off.schedule_id for r in logs)
    assert len(w.notifications(family)) == (1 if considered else 0)
    assert len(w.pushes.alerts_to(family_token)) == (1 if considered else 0)
    assert w.pushes.syncs_to(patient_token) == [] and w.pending() == []
