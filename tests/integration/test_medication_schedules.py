"""Ghi từng lịch, đổi ngày uống, mốc hiệu lực, dùng lại thuốc (task 2.04: AC1–AC11, AC17,
AC20, AC21, AC24–AC29).

Mọi khẳng định theo contract (`api_contract/openapi.json`) và trạng thái DB. Lịch có hiệu lực
trong khoảng nửa mở [effective_from, ended_at); đóng lịch không xoá dòng.
"""

import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

ALL_WEEK = [1, 2, 3, 4, 5, 6, 7]


@pytest.fixture
def med(client, make, auth, scheduled_body):
    """Người bệnh P, thuốc X theo giờ có S1 08:00, S2 20:00 cả tuần, một liều quá khứ trỏ S1."""
    patient = make.user()
    r = client.post(
        "/medications", json=scheduled_body(make.catalog_medication()), headers=auth(patient)
    )
    assert r.status_code == 201, r.text
    out = r.json()
    s1, s2 = (s["id"] for s in out["schedules"])
    dose = make.dose_log(s1, datetime.now(UTC) - timedelta(days=1))
    return {"patient": patient, "id": out["id"], "s1": s1, "s2": s2, "dose": dose}


def _open(make, med_id):
    return [s for s in make.schedules(med_id) if s["ended_at"] is None]


def _row(make, med_id, schedule_id):
    return next(s for s in make.schedules(med_id) if s["id"] == schedule_id)


def _snapshot(make, m):
    return (make.counts(m["patient"]), make.schedules(m["id"]), make.medication_row(m["id"]))


def _db_now(db):
    return db.execute(text("SELECT clock_timestamp()")).scalar_one()


def _in_thread(fn):
    result = {}

    def run():
        result["response"] = fn()

    t = threading.Thread(target=run)
    t.start()
    return t, result


def _parallel(*calls):
    barrier = threading.Barrier(len(calls))

    def wrap(call):
        def go():
            barrier.wait()
            return call()

        return go

    threads = [_in_thread(wrap(c)) for c in calls]
    for t, _ in threads:
        t.join(timeout=20)
    return [res["response"] for _, res in threads]


# --- POST /medications/{id}/schedules -------------------------------------------------------


@pytest.mark.parametrize("reminder", [None, False])
def test_add_schedule__AC1(client, db, make, auth, med, reminder):
    body = {"intake_time": "12:00"} | ({} if reminder is None else {"reminder_enabled": reminder})
    before = _db_now(db)
    r = client.post(f"/medications/{med['id']}/schedules", json=body, headers=auth(med["patient"]))
    after = _db_now(db)
    assert r.status_code == 201, r.text
    out = r.json()
    assert [s["intake_time"] for s in out["schedules"]] == ["08:00", "12:00", "20:00"]
    assert out["doses_per_day"] == 3
    new = next(s for s in _open(make, med["id"]) if s["intake_time"] == "12:00")
    assert new["days_of_week"] == ALL_WEEK
    assert new["reminder_enabled"] is (reminder is not False)
    assert before <= new["effective_from"] <= after
    assert {s["id"] for s in _open(make, med["id"])} == {med["s1"], med["s2"], new["id"]}
    assert make.medication_row(med["id"])["doses_per_day"] == 3


@pytest.mark.parametrize(
    "body, code",
    [
        ({"intake_time": "08:00"}, "schedule_time_conflict"),
        ({}, None),
        ({"intake_time": "24:00"}, None),
        ({"intake_time": "08:00", "days_of_week": [1]}, None),
        ({"intake_time": "09:00", "foo": 1}, None),
    ],
)
def test_add_schedule_rejected_writes_nothing__AC2(client, make, auth, med, body, code):
    before = _snapshot(make, med)
    r = client.post(f"/medications/{med['id']}/schedules", json=body, headers=auth(med["patient"]))
    assert r.status_code == 422
    if code:
        assert r.json() == {"detail": code}
    else:
        assert isinstance(r.json()["detail"], list)
    assert _snapshot(make, med) == before


def test_add_schedule_limit_reached__AC2(client, make, auth, scheduled_body):
    patient = make.user()
    times = ["06:00", "08:00", "10:00", "12:00", "14:00", "16:00"]
    m = client.post(
        "/medications",
        json=scheduled_body(make.catalog_medication(), intake_times=times),
        headers=auth(patient),
    ).json()
    before = make.schedules(m["id"])
    r = client.post(
        f"/medications/{m['id']}/schedules", json={"intake_time": "18:00"}, headers=auth(patient)
    )
    assert r.status_code == 422 and r.json() == {"detail": "schedule_limit_reached"}
    assert make.schedules(m["id"]) == before


def test_add_schedule_as_needed_422__AC2(client, make, auth, as_needed_body):
    patient = make.user()
    m = client.post(
        "/medications", json=as_needed_body(make.catalog_medication()), headers=auth(patient)
    ).json()
    r = client.post(
        f"/medications/{m['id']}/schedules", json={"intake_time": "08:00"}, headers=auth(patient)
    )
    assert r.status_code == 422 and r.json() == {"detail": "medication_rule_violation"}
    assert make.schedules(m["id"]) == []


def test_stopped_medication_schedule_writes_422__AC8(client, make, auth, med):
    h = auth(med["patient"])
    assert (
        client.patch(f"/medications/{med['id']}", json={"stopped": True}, headers=h).status_code
        == 200
    )
    before = _snapshot(make, med)
    for method, path, body in [
        ("post", f"/medications/{med['id']}/schedules", {"intake_time": "12:00"}),
        ("patch", f"/medications/{med['id']}/schedules/{med['s1']}", {"intake_time": "07:00"}),
        ("delete", f"/medications/{med['id']}/schedules/{med['s1']}", None),
    ]:
        r = client.request(method, path, json=body, headers=h)
        assert r.status_code == 422 and r.json() == {"detail": "medication_stopped"}, method
    assert _snapshot(make, med) == before


# --- PATCH /medications/{id}/schedules/{schedule_id} ----------------------------------------


def test_edit_time_versions_schedule_and_keeps_dose_logs__AC3(client, make, auth, med):
    r = client.patch(
        f"/medications/{med['id']}/schedules/{med['s1']}",
        json={"intake_time": "07:00"},
        headers=auth(med["patient"]),
    )
    assert r.status_code == 200, r.text
    out = r.json()
    old = _row(make, med["id"], med["s1"])
    assert old["ended_at"] is not None  # đóng, không xoá
    new = next(s for s in _open(make, med["id"]) if s["intake_time"] == "07:00")
    assert new["id"] != med["s1"]
    assert new["effective_from"] == old["ended_at"]
    assert (new["days_of_week"], new["reminder_enabled"]) == (ALL_WEEK, True)
    assert _row(make, med["id"], med["s2"])["ended_at"] is None
    assert [s["id"] for s in out["schedules"]] == [new["id"], med["s2"]]
    assert out["doses_per_day"] == 2 and make.medication_row(med["id"])["doses_per_day"] == 2
    assert [d["medication_schedule_id"] for d in make.dose_logs_of(med["id"])] == [med["s1"]]


def test_toggle_reminder_versions_schedule__AC4(client, make, auth, med):
    h = auth(med["patient"])
    r = client.patch(
        f"/medications/{med['id']}/schedules/{med['s1']}",
        json={"reminder_enabled": False},
        headers=h,
    )
    assert r.status_code == 200, r.text
    off = next(s for s in r.json()["schedules"] if s["intake_time"] == "08:00")
    assert off["reminder_enabled"] is False and off["id"] != med["s1"]
    assert _row(make, med["id"], med["s1"])["ended_at"] is not None
    r = client.patch(
        f"/medications/{med['id']}/schedules/{off['id']}",
        json={"reminder_enabled": True},
        headers=h,
    )
    on = next(s for s in r.json()["schedules"] if s["intake_time"] == "08:00")
    assert on["reminder_enabled"] is True and on["id"] not in (med["s1"], off["id"])
    assert len(_open(make, med["id"])) == 2 and len(make.schedules(med["id"])) == 4


@pytest.mark.parametrize(
    "body",
    [
        {"reminder_enabled": True},
        {"intake_time": "20:00"},
        {"intake_time": "20:00", "reminder_enabled": True},
    ],
)
def test_edit_same_values_noop__AC4(client, make, auth, med, body):
    before = _snapshot(make, med)
    r = client.patch(
        f"/medications/{med['id']}/schedules/{med['s2']}", json=body, headers=auth(med["patient"])
    )
    assert r.status_code == 200
    assert med["s2"] in [s["id"] for s in r.json()["schedules"]]
    assert _snapshot(make, med) == before


@pytest.mark.parametrize(
    "body, code",
    [
        ({"intake_time": "20:00"}, "schedule_time_conflict"),
        ({}, None),
        ({"intake_time": "7h"}, None),
        ({"reminder_enabled": False, "x": 1}, None),
    ],
)
def test_edit_invalid_writes_nothing__AC5(client, make, auth, med, body, code):
    before = _snapshot(make, med)
    r = client.patch(
        f"/medications/{med['id']}/schedules/{med['s1']}", json=body, headers=auth(med["patient"])
    )
    assert r.status_code == 422
    assert r.json() == {"detail": code} if code else isinstance(r.json()["detail"], list)
    assert _snapshot(make, med) == before


def test_closed_or_foreign_schedule_404_changes_nothing__AC6(
    client, make, auth, med, scheduled_body
):
    h = auth(med["patient"])
    client.patch(
        f"/medications/{med['id']}/schedules/{med['s1']}", json={"intake_time": "07:00"}, headers=h
    )
    other = client.post(
        "/medications", json=scheduled_body(make.catalog_medication()), headers=h
    ).json()
    foreign = other["schedules"][0]["id"]
    before = (_snapshot(make, med), make.schedules(other["id"]))
    for sid in (med["s1"], foreign, 2**62):
        for method, body in (("patch", {"intake_time": "09:00"}), ("delete", None)):
            r = client.request(
                method, f"/medications/{med['id']}/schedules/{sid}", json=body, headers=h
            )
            assert r.status_code == 404, (sid, method)
            assert r.json() == {"detail": "medication_schedule_not_found"}
    assert (_snapshot(make, med), make.schedules(other["id"])) == before


# --- DELETE /medications/{id}/schedules/{schedule_id} ---------------------------------------


def test_remove_schedule__AC7(client, make, auth, med):
    h = auth(med["patient"])
    r = client.delete(f"/medications/{med['id']}/schedules/{med['s2']}", headers=h)
    assert r.status_code == 200, r.text
    assert [s["id"] for s in r.json()["schedules"]] == [med["s1"]]
    assert r.json()["doses_per_day"] == 1
    assert _row(make, med["id"], med["s2"])["ended_at"] is not None
    got = client.get(f"/medications/{med['id']}", headers=h).json()
    assert [s["id"] for s in got["schedules"]] == [med["s1"]]
    assert make.medication_row(med["id"])["doses_per_day"] == 1
    assert len(make.dose_logs_of(med["id"])) == 1


def test_remove_last_schedule_422__AC8(client, make, auth, med):
    h = auth(med["patient"])
    client.delete(f"/medications/{med['id']}/schedules/{med['s2']}", headers=h)
    before = _snapshot(make, med)
    r = client.delete(f"/medications/{med['id']}/schedules/{med['s1']}", headers=h)
    assert r.status_code == 422 and r.json() == {"detail": "last_schedule_not_removable"}
    assert _snapshot(make, med) == before


# --- PATCH /medications/{id}: days_of_week, giữ trạng thái nhắc -----------------------------


def test_patch_days_of_week__AC9(client, make, auth, med):
    h = auth(med["patient"])
    client.patch(
        f"/medications/{med['id']}/schedules/{med['s2']}",
        json={"reminder_enabled": False},
        headers=h,
    )
    open_before = {s["id"] for s in _open(make, med["id"])}
    r = client.patch(f"/medications/{med['id']}", json={"days_of_week": [5, 1, 3]}, headers=h)
    assert r.status_code == 200, r.text
    opened = _open(make, med["id"])
    assert [(s["intake_time"], s["days_of_week"], s["reminder_enabled"]) for s in opened] == [
        ("08:00", [1, 3, 5], True),
        ("20:00", [1, 3, 5], False),
    ]
    assert not ({s["id"] for s in opened} & open_before)
    ends = {s["ended_at"] for s in make.schedules(med["id"]) if s["id"] in open_before} - {None}
    assert len(ends) == 1 and all(s["effective_from"] in ends for s in opened)
    assert make.medication_row(med["id"])["doses_per_day"] == 2
    # cùng ngày: không đổi gì
    before = make.schedules(med["id"])
    assert (
        client.patch(
            f"/medications/{med['id']}", json={"days_of_week": [1, 3, 5]}, headers=h
        ).status_code
        == 200
    )
    assert make.schedules(med["id"]) == before
    # kèm intake_times
    r = client.patch(
        f"/medications/{med['id']}",
        json={"intake_times": ["09:00"], "days_of_week": [6, 7]},
        headers=h,
    )
    assert [(s["intake_time"], s["days_of_week"]) for s in r.json()["schedules"]] == [
        ("09:00", [6, 7])
    ]


@pytest.mark.parametrize(
    "body, code",
    [
        ({"days_of_week": []}, None),
        ({"days_of_week": [8]}, None),
        ({"days_of_week": [1, 1]}, None),
        (
            {"dosing_mode": "as_needed", "max_doses_per_day": 2, "days_of_week": [1]},
            "medication_rule_violation",
        ),
    ],
)
def test_patch_days_invalid_writes_nothing__AC9(client, make, auth, med, body, code):
    before = _snapshot(make, med)
    r = client.patch(f"/medications/{med['id']}", json=body, headers=auth(med["patient"]))
    assert r.status_code == 422
    assert r.json() == {"detail": code} if code else isinstance(r.json()["detail"], list)
    assert _snapshot(make, med) == before


def test_patch_days_on_as_needed_422__AC9(client, make, auth, as_needed_body):
    patient = make.user()
    m = client.post(
        "/medications", json=as_needed_body(make.catalog_medication()), headers=auth(patient)
    ).json()
    r = client.patch(f"/medications/{m['id']}", json={"days_of_week": [1]}, headers=auth(patient))
    assert r.status_code == 422 and r.json() == {"detail": "medication_rule_violation"}


def test_patch_times_keeps_reminder__AC10(client, make, auth, med):
    h = auth(med["patient"])
    client.patch(
        f"/medications/{med['id']}/schedules/{med['s2']}",
        json={"reminder_enabled": False},
        headers=h,
    )
    r = client.patch(
        f"/medications/{med['id']}", json={"intake_times": ["08:00", "20:00", "22:00"]}, headers=h
    )
    assert r.status_code == 200, r.text
    assert [(s["intake_time"], s["reminder_enabled"]) for s in r.json()["schedules"]] == [
        ("08:00", True),
        ("20:00", False),
        ("22:00", True),
    ]


# --- Chạy đua (AC11) ------------------------------------------------------------------------


def _assert_consistent(make, med_id):
    opened = _open(make, med_id)
    times = [s["intake_time"] for s in opened]
    assert len(times) == len(set(times)) and len(opened) >= 1
    assert make.medication_row(med_id)["doses_per_day"] == len(opened)


def test_two_adds_same_time_one_wins__AC11(client, make, auth, med):
    h = auth(med["patient"])
    responses = _parallel(
        *[
            lambda: client.post(
                f"/medications/{med['id']}/schedules", json={"intake_time": "12:00"}, headers=h
            )
            for _ in range(2)
        ]
    )
    assert sorted(r.status_code for r in responses) == [201, 422]
    assert [s["intake_time"] for s in _open(make, med["id"])].count("12:00") == 1
    _assert_consistent(make, med["id"])


def test_remove_both_schedules_one_wins__AC11(client, make, auth, med):
    h = auth(med["patient"])
    responses = _parallel(
        lambda: client.delete(f"/medications/{med['id']}/schedules/{med['s1']}", headers=h),
        lambda: client.delete(f"/medications/{med['id']}/schedules/{med['s2']}", headers=h),
    )
    assert sorted(r.status_code for r in responses) == [200, 422]
    assert len(_open(make, med["id"])) == 1
    _assert_consistent(make, med["id"])


def test_edit_schedule_and_change_days_serialized__AC11(client, make, auth, med):
    h = auth(med["patient"])
    responses = _parallel(
        lambda: client.patch(
            f"/medications/{med['id']}/schedules/{med['s1']}",
            json={"intake_time": "07:00"},
            headers=h,
        ),
        lambda: client.patch(f"/medications/{med['id']}", json={"days_of_week": [2, 4]}, headers=h),
    )
    codes = [r.status_code for r in responses]
    assert codes[1] == 200 and codes[0] in (200, 404), codes
    assert all(r.status_code < 500 for r in responses)
    opened = _open(make, med["id"])
    assert all(s["days_of_week"] == [2, 4] for s in opened)
    assert [s["intake_time"] for s in opened] in (["07:00", "20:00"], ["08:00", "20:00"])
    _assert_consistent(make, med["id"])


# --- Rollback (AC17) ------------------------------------------------------------------------


@pytest.mark.parametrize("op", ["edit", "days"])
def test_failure_after_close_rolls_back__AC17(make, auth, med, monkeypatch, op):
    from fastapi.testclient import TestClient

    from drugtime.main import create_app
    from drugtime.modules.medication.adapters.outbound.sql_medication import SqlMedication

    def broken(*_args, **_kwargs):
        raise RuntimeError("insert failed")

    monkeypatch.setattr(SqlMedication, "add_schedules", broken)
    client = TestClient(create_app(), raise_server_exceptions=False)
    before = _snapshot(make, med)
    h = auth(med["patient"])
    if op == "edit":
        r = client.patch(
            f"/medications/{med['id']}/schedules/{med['s1']}",
            json={"intake_time": "07:00"},
            headers=h,
        )
    else:
        r = client.patch(f"/medications/{med['id']}", json={"days_of_week": [1]}, headers=h)
    assert r.status_code == 500
    assert _snapshot(make, med) == before


# --- Mốc hiệu lực theo liều xác nhận sớm (QD-16, AC20, AC21) --------------------------------


@pytest.fixture
def early(make, med):
    """Liều của S1 đã xác nhận sớm, giờ dự kiến 10 phút sau thời điểm hiện tại."""
    at = datetime.now(UTC).replace(microsecond=0) + timedelta(minutes=10)
    make.dose_log(med["s1"], at, status="da_uong")
    return at


@pytest.mark.parametrize("body", [{"reminder_enabled": False}, {"intake_time": "07:55"}])
def test_early_dose_edit_shifts_boundary__AC20(client, make, auth, med, early, body):
    r = client.patch(
        f"/medications/{med['id']}/schedules/{med['s1']}", json=body, headers=auth(med["patient"])
    )
    assert r.status_code == 200, r.text
    old = _row(make, med["id"], med["s1"])
    assert old["ended_at"] == early + timedelta(seconds=1)
    new = next(s for s in _open(make, med["id"]) if s["id"] not in (med["s1"], med["s2"]))
    assert new["effective_from"] == old["ended_at"]
    # liều vẫn thuộc S1 và nằm trong khoảng hiệu lực của S1
    dose = next(d for d in make.dose_logs_of(med["id"]) if d["scheduled_at"] == early)
    assert dose["medication_schedule_id"] == med["s1"]
    assert old["effective_from"] <= dose["scheduled_at"] < old["ended_at"]
    # response và GET đều thấy effective_from ở tương lai
    shown = next(s for s in r.json()["schedules"] if s["id"] == new["id"])
    assert datetime.fromisoformat(shown["effective_from"]) == old["ended_at"]


@pytest.mark.parametrize("body", [{"days_of_week": [1, 2]}, {"intake_times": ["09:00", "21:00"]}])
def test_early_dose_bulk_replace_starts_after_dose__AC20(client, make, auth, med, early, body):
    r = client.patch(f"/medications/{med['id']}", json=body, headers=auth(med["patient"]))
    assert r.status_code == 200, r.text
    end1 = _row(make, med["id"], med["s1"])["ended_at"]
    end2 = _row(make, med["id"], med["s2"])["ended_at"]
    assert end1 == early + timedelta(seconds=1) and end2 < end1
    assert {s["effective_from"] for s in _open(make, med["id"])} == {end1}


def test_delete_then_add_same_time_no_overlap__AC21(client, make, auth, med, early):
    h = auth(med["patient"])
    assert (
        client.delete(f"/medications/{med['id']}/schedules/{med['s1']}", headers=h).status_code
        == 200
    )
    end = _row(make, med["id"], med["s1"])["ended_at"]
    assert end == early + timedelta(seconds=1)
    r = client.post(f"/medications/{med['id']}/schedules", json={"intake_time": "08:00"}, headers=h)
    assert r.status_code == 201, r.text
    new = next(s for s in _open(make, med["id"]) if s["intake_time"] == "08:00")
    assert new["effective_from"] == end


def _no_overlap(make, med_id):
    """Không giờ dự kiến nào thuộc hai lịch cùng giờ của một thuốc: các khoảng hiệu lực
    [effective_from, ended_at) cùng giờ không chồng nhau."""
    by_time = {}
    for s in make.schedules(med_id):
        by_time.setdefault(s["intake_time"], []).append(s)
    for rows in by_time.values():
        rows.sort(key=lambda s: s["effective_from"])
        for a, b in zip(rows, rows[1:], strict=False):
            assert a["ended_at"] is not None and a["ended_at"] <= b["effective_from"], (a, b)


def _dose_inside_own_schedule(make, med_id, at):
    dose = next(d for d in make.dose_logs_of(med_id) if d["scheduled_at"] == at)
    own = _row(make, med_id, dose["medication_schedule_id"])
    assert own["effective_from"] <= at and (own["ended_at"] is None or at < own["ended_at"])
    return dose


def test_stop_and_reactivate_after_future_replacement(client, make, auth, med, early):
    """Ngừng ngay sau khi có lịch hiệu lực ở tương lai (S1 vừa được thay vì tắt nhắc sau liều
    sớm) rồi dùng lại: không lỗi CHECK, mở đúng một lịch mỗi giờ theo kế hoạch mới nhất, và
    không giờ dự kiến nào thuộc hai lịch (M1 của review)."""
    h = auth(med["patient"])
    client.patch(
        f"/medications/{med['id']}/schedules/{med['s1']}",
        json={"reminder_enabled": False},
        headers=h,
    )
    r = client.patch(f"/medications/{med['id']}", json={"stopped": True}, headers=h)
    assert r.status_code == 200, r.text
    assert _open(make, med["id"]) == []
    r = client.patch(f"/medications/{med['id']}", json={"stopped": False}, headers=h)
    assert r.status_code == 200, r.text
    assert [(s["intake_time"], s["reminder_enabled"]) for s in r.json()["schedules"]] == [
        ("08:00", False),
        ("20:00", True),
    ]
    new_0800 = next(s for s in _open(make, med["id"]) if s["intake_time"] == "08:00")
    assert new_0800["effective_from"] == early + timedelta(seconds=1)
    _dose_inside_own_schedule(make, med["id"], early)
    _no_overlap(make, med["id"])


@pytest.mark.parametrize("op", ["stop", "as_needed", "delete"])
def test_stop_switch_or_delete_after_early_dose_keeps_dose_inside__AC24(
    client, db, make, auth, med, early, op
):
    h = auth(med["patient"])
    before = _db_now(db)
    if op == "delete":
        r = client.delete(f"/medications/{med['id']}", headers=h)
        assert r.status_code == 204
    else:
        body = (
            {"stopped": True}
            if op == "stop"
            else {"dosing_mode": "as_needed", "max_doses_per_day": 2}
        )
        r = client.patch(f"/medications/{med['id']}", json=body, headers=h)
        assert r.status_code == 200, r.text
    after = _db_now(db)
    s1, s2 = _row(make, med["id"], med["s1"]), _row(make, med["id"], med["s2"])
    assert s1["ended_at"] == early + timedelta(seconds=1)
    assert before <= s2["ended_at"] <= after
    _dose_inside_own_schedule(make, med["id"], early)
    row = make.medication_row(med["id"])
    if op != "as_needed":
        assert before <= row["ended_at"] <= after and row["ended_at"] < s1["ended_at"]
    if op == "delete":
        assert row["deleted_at"] == row["ended_at"]


def test_reactivate_after_early_dose_no_overlap__AC25(client, db, make, auth, med, early):
    h = auth(med["patient"])
    assert (
        client.patch(f"/medications/{med['id']}", json={"stopped": True}, headers=h).status_code
        == 200
    )
    end_s1 = _row(make, med["id"], med["s1"])["ended_at"]
    before = _db_now(db)
    r = client.patch(f"/medications/{med['id']}", json={"stopped": False}, headers=h)
    after = _db_now(db)
    assert r.status_code == 200, r.text
    opened = {s["intake_time"]: s for s in _open(make, med["id"])}
    assert set(opened) == {"08:00", "20:00"}
    assert opened["08:00"]["effective_from"] == end_s1 == early + timedelta(seconds=1)
    assert before <= opened["20:00"]["effective_from"] <= after
    assert all(s["reminder_enabled"] for s in opened.values())
    _dose_inside_own_schedule(make, med["id"], early)
    _no_overlap(make, med["id"])


def test_back_to_scheduled_after_early_dose_no_overlap__AC26(client, db, make, auth, med, early):
    h = auth(med["patient"])
    r = client.patch(
        f"/medications/{med['id']}",
        json={"dosing_mode": "as_needed", "max_doses_per_day": 2},
        headers=h,
    )
    assert r.status_code == 200, r.text
    end_s1 = _row(make, med["id"], med["s1"])["ended_at"]
    before = _db_now(db)
    r = client.patch(
        f"/medications/{med['id']}",
        json={"dosing_mode": "scheduled", "intake_times": ["08:00", "20:00"]},
        headers=h,
    )
    after = _db_now(db)
    assert r.status_code == 200, r.text
    opened = {s["intake_time"]: s for s in _open(make, med["id"])}
    assert opened["08:00"]["effective_from"] == end_s1 == early + timedelta(seconds=1)
    assert before <= opened["20:00"]["effective_from"] <= after
    _dose_inside_own_schedule(make, med["id"], early)
    _no_overlap(make, med["id"])


def test_reactivate_as_needed_after_early_dose_opens_no_schedule__R2(
    client, make, auth, med, early
):
    """Chuyển sang khi cần (sau liều sớm) → ngừng → dùng lại trước giờ của liều: thuốc khi cần
    không có lịch mở (contract: "Thuốc as_needed: không tạo lịch"; R2 của review vòng 3)."""
    h = auth(med["patient"])
    r = client.patch(
        f"/medications/{med['id']}",
        json={"dosing_mode": "as_needed", "max_doses_per_day": 2},
        headers=h,
    )
    assert r.status_code == 200, r.text
    assert (
        client.patch(f"/medications/{med['id']}", json={"stopped": True}, headers=h).status_code
        == 200
    )
    r = client.patch(f"/medications/{med['id']}", json={"stopped": False}, headers=h)
    assert r.status_code == 200, r.text
    out = r.json()
    assert (out["dosing_mode"], out["status"], out["schedules"]) == ("as_needed", "active", [])
    assert _open(make, med["id"]) == []
    assert make.medication_row(med["id"])["ended_at"] is None
    _dose_inside_own_schedule(make, med["id"], early)


# --- Dùng lại theo dấu "đóng do ngừng" (vòng 4: R3, M3; AC27–AC29) ----------------------------


def _markers(db, med_id):
    rows = db.execute(
        text(
            "SELECT id, closed_by_stop_at FROM medication_schedules "
            "WHERE user_medication_id = :i ORDER BY id"
        ),
        {"i": med_id},
    )
    return {r.id: r.closed_by_stop_at for r in rows}


def _stop_then_reactivate(client, h, med_id):
    r = client.patch(f"/medications/{med_id}", json={"stopped": True}, headers=h)
    assert r.status_code == 200, r.text
    r = client.patch(f"/medications/{med_id}", json={"stopped": False}, headers=h)
    assert r.status_code == 200, r.text
    return r.json()


@pytest.mark.parametrize(
    ("body", "times", "days"),
    [
        ({"intake_times": ["07:00", "22:00"]}, ["07:00", "22:00"], ALL_WEEK),
        ({"days_of_week": [1, 2]}, ["08:00", "20:00"], [1, 2]),
    ],
)
def test_reactivate_after_bulk_change_after_early_dose_keeps_all__AC27(
    client, make, auth, med, early, body, times, days
):
    """Seed 43 của review vòng 4: liều sớm → đổi cả bộ giờ/ngày (lịch mới bắt đầu ở tương lai)
    → ngừng → dùng lại: mở lại đủ mọi lịch, doses_per_day khớp số lịch."""
    h = auth(med["patient"])
    r = client.patch(f"/medications/{med['id']}", json=body, headers=h)
    assert r.status_code == 200, r.text
    out = _stop_then_reactivate(client, h, med["id"])
    assert [s["intake_time"] for s in out["schedules"]] == times
    assert all(s["days_of_week"] == days for s in out["schedules"])
    assert out["doses_per_day"] == len(times) == len(_open(make, med["id"]))
    _dose_inside_own_schedule(make, med["id"], early)
    _no_overlap(make, med["id"])


@pytest.mark.parametrize("variant", ["edit_then_add", "remove_then_add_same_time"])
def test_reactivate_after_single_schedule_writes_with_future_schedule__AC27(
    client, make, auth, med, early, variant
):
    h = auth(med["patient"])
    base = f"/medications/{med['id']}/schedules"
    if variant == "edit_then_add":
        r = client.patch(f"{base}/{med['s1']}", json={"intake_time": "07:55"}, headers=h)
        assert r.status_code == 200, r.text
        r = client.post(base, json={"intake_time": "12:00"}, headers=h)
        expected = ["07:55", "12:00", "20:00"]
    else:
        assert client.delete(f"{base}/{med['s1']}", headers=h).status_code == 200
        r = client.post(base, json={"intake_time": "08:00"}, headers=h)
        expected = ["08:00", "20:00"]
    assert r.status_code == 201, r.text
    out = _stop_then_reactivate(client, h, med["id"])
    assert [s["intake_time"] for s in out["schedules"]] == expected
    assert out["doses_per_day"] == len(expected)
    _dose_inside_own_schedule(make, med["id"], early)
    _no_overlap(make, med["id"])


def test_reactivate_skips_schedules_replaced_before_stop_and_marks__AC28(
    client, db, make, auth, med
):
    h = auth(med["patient"])
    r = client.patch(
        f"/medications/{med['id']}/schedules/{med['s1']}", json={"intake_time": "07:00"}, headers=h
    )
    assert r.status_code == 200, r.text
    r = client.patch(f"/medications/{med['id']}", json={"stopped": True}, headers=h)
    assert r.status_code == 200, r.text
    stopped_at = make.medication_row(med["id"])["ended_at"]
    marks = _markers(db, med["id"])
    assert marks[med["s1"]] is None  # đóng vì sửa lịch, không mang dấu
    assert [i for i, m in marks.items() if m is not None] == [i for i in marks if i != med["s1"]]
    assert all(m == stopped_at for i, m in marks.items() if i != med["s1"])
    r = client.patch(f"/medications/{med['id']}", json={"stopped": False}, headers=h)
    assert r.status_code == 200, r.text
    out = r.json()
    assert [s["intake_time"] for s in out["schedules"]] == ["07:00", "20:00"]
    assert out["doses_per_day"] == 2
    assert all("closed_by_stop_at" not in s for s in out["schedules"])
    # lịch mở lại không mang dấu
    assert all(_markers(db, med["id"])[s["id"]] is None for s in out["schedules"])


def _migration_backfill_sql():
    path = next(
        (Path(__file__).parents[2] / "supabase" / "migrations").glob(
            "*_medication_schedules_closed_by_stop.sql"
        )
    )
    statements = [s.strip() for s in path.read_text(encoding="utf-8").split(";")]
    return next(s for s in statements if "UPDATE medication_schedules" in s)


def test_backfill_marks_pre_migration_stop__AC29(client, db, make, auth, med):
    """Dữ liệu ngừng trước migration (lịch đóng đúng lúc ngừng, chưa có dấu): câu điền dữ liệu
    của migration đánh dấu lại, và dùng lại mở đúng các lịch như 2.01."""
    h = auth(med["patient"])
    r = client.patch(f"/medications/{med['id']}", json={"stopped": True}, headers=h)
    assert r.status_code == 200, r.text
    db.execute(
        text(
            "UPDATE medication_schedules SET closed_by_stop_at = NULL WHERE user_medication_id = :i"
        ),
        {"i": med["id"]},
    )
    db.execute(text(_migration_backfill_sql()))
    db.commit()
    stopped_at = make.medication_row(med["id"])["ended_at"]
    assert set(_markers(db, med["id"]).values()) == {stopped_at}
    r = client.patch(f"/medications/{med['id']}", json={"stopped": False}, headers=h)
    assert r.status_code == 200, r.text
    assert [s["intake_time"] for s in r.json()["schedules"]] == ["08:00", "20:00"]
    assert r.json()["doses_per_day"] == 2


def test_marker_requires_closed_schedule_check(db, med):
    with pytest.raises(IntegrityError, match="medication_schedules_closed_by_stop_chk"):
        db.execute(
            text("UPDATE medication_schedules SET closed_by_stop_at = now() WHERE id = :s"),
            {"s": med["s1"]},
        )
    db.rollback()
