"""Chống tạo trùng, chạy đua và rollback của POST /medications (AC4, AC8b–AC8d, AC19).

Chạy đua được dựng tất định: kết nối A giữ một transaction chưa commit, request B chạy trong
thread và bị khóa; khi thấy B đang chờ khóa thì A commit.
"""

import threading
import time
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text

from drugtime.modules.medication.adapters.outbound.sql_medication import SqlMedication


@pytest.fixture
def tx(admin_engine):
    """Kết nối có transaction thật (không autocommit) để giữ khóa."""
    conn = admin_engine.execution_options(isolation_level="READ COMMITTED").connect()
    yield conn
    conn.close()


def _wait_until_blocked(db, timeout=10.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        waiting = db.execute(
            text(
                "SELECT count(*) FROM pg_stat_activity "
                "WHERE usename = 'api_role' AND wait_event_type = 'Lock'"
            )
        ).scalar_one()
        if waiting:
            return
        time.sleep(0.05)
    raise AssertionError("request B never waited on the lock")


def _in_thread(fn):
    result = {}

    def run():
        result["response"] = fn()

    t = threading.Thread(target=run)
    t.start()
    return t, result


def _insert_default_prescription(conn, user_id):
    return conn.execute(
        text(
            "INSERT INTO prescriptions (user_id, entry_source) VALUES (:u, 'mac_dinh') RETURNING id"
        ),
        {"u": user_id},
    ).scalar_one()


def test_replay_same_client_uuid_returns_200_same_medication__AC8b(
    client, make, auth, scheduled_body, as_needed_body
):
    patient = make.user()
    body = scheduled_body(make.catalog_medication())
    first = client.post("/medications", json=body, headers=auth(patient))
    assert first.status_code == 201
    before = make.counts(patient)

    # Body khác hẳn (khi cần, thuốc khác) nhưng cùng client_uuid: bị bỏ qua.
    other = as_needed_body(make.catalog_medication(), client_uuid=body["client_uuid"])
    for replay in (body, other):
        r = client.post("/medications", json=replay, headers=auth(patient))
        assert r.status_code == 200, r.text
        assert r.json() == first.json()
        assert r.headers["Location"] == first.headers["Location"]
    assert make.counts(patient) == before


def test_replay_after_stop_returns_current_state(client, make, auth, scheduled_body):
    patient = make.user()
    body = scheduled_body(make.catalog_medication())
    med = client.post("/medications", json=body, headers=auth(patient)).json()
    client.patch(f"/medications/{med['id']}", json={"stopped": True}, headers=auth(patient))
    r = client.post("/medications", json=body, headers=auth(patient))
    assert r.status_code == 200 and r.json()["status"] == "stopped"


def test_replay_after_catalog_soft_delete_still_returns_medication(
    client, db, make, auth, scheduled_body
):
    patient = make.user()
    drug = make.catalog_medication()
    body = scheduled_body(drug)
    first = client.post("/medications", json=body, headers=auth(patient)).json()
    db.execute(text("UPDATE medications SET deleted_at = now() WHERE id = :m"), {"m": drug})
    r = client.post("/medications", json=body, headers=auth(patient))
    assert r.status_code == 200 and r.json() == first


def test_concurrent_same_client_uuid_single_row__AC8c(client, tx, db, make, auth, scheduled_body):
    patient = make.user()
    drug = make.catalog_medication()
    body = scheduled_body(drug)

    # A: "request đầu" đã ghi đơn mặc định và thuốc nhưng chưa commit.
    tx.begin()
    prescription = _insert_default_prescription(tx, patient)
    winner = tx.execute(
        text(
            "INSERT INTO user_medications (user_id, prescription_id, medication_id, "
            "entry_method, confirmation_status, quantity_per_dose, doses_per_day, client_uuid) "
            "VALUES (:u, :p, :m, 'thu_cong', 'da_xac_nhan', 1, 2, :c) RETURNING id"
        ),
        {"u": patient, "p": prescription, "m": drug, "c": UUID(body["client_uuid"])},
    ).scalar_one()

    t, result = _in_thread(lambda: client.post("/medications", json=body, headers=auth(patient)))
    _wait_until_blocked(db)
    tx.commit()
    t.join(timeout=15)

    r = result["response"]
    assert r.status_code == 200, r.text
    assert r.json()["id"] == winner
    assert make.counts(patient) == {"meds": 1, "schedules": 0, "prescriptions": 1}


def test_two_parallel_requests_same_client_uuid__AC8c(client, make, auth, scheduled_body):
    """Hai request HTTP thật gửi cùng lúc: một 201, một 200, cùng một thuốc, không 5xx."""
    patient = make.user()
    body = scheduled_body(make.catalog_medication())
    barrier = threading.Barrier(2)

    def send():
        barrier.wait()
        return client.post("/medications", json=body, headers=auth(patient))

    threads = [_in_thread(send) for _ in range(2)]
    for t, _ in threads:
        t.join(timeout=15)
    responses = [res["response"] for _, res in threads]
    assert sorted(r.status_code for r in responses) == [200, 201]
    assert responses[0].json()["id"] == responses[1].json()["id"]
    assert make.counts(patient) == {"meds": 1, "schedules": 2, "prescriptions": 1}


def test_concurrent_first_medications_single_default_prescription__AC4(
    client, tx, db, make, auth, scheduled_body
):
    patient = make.user()
    tx.begin()
    prescription = _insert_default_prescription(tx, patient)

    body = scheduled_body(make.catalog_medication())
    t, result = _in_thread(lambda: client.post("/medications", json=body, headers=auth(patient)))
    _wait_until_blocked(db)
    tx.commit()
    t.join(timeout=15)

    r = result["response"]
    assert r.status_code == 201, r.text
    used = db.execute(
        text("SELECT prescription_id FROM user_medications WHERE id = :i"), {"i": r.json()["id"]}
    ).scalar_one()
    assert used == prescription
    assert make.counts(patient)["prescriptions"] == 1


def test_client_uuid_scoped_per_user__AC8d(client, make, auth, scheduled_body):
    q, p = make.user(), make.user()
    shared = str(uuid4())
    q_med = client.post(
        "/medications",
        json=scheduled_body(make.catalog_medication(), client_uuid=shared),
        headers=auth(q),
    ).json()
    r = client.post(
        "/medications",
        json=scheduled_body(make.catalog_medication(), client_uuid=shared),
        headers=auth(p),
    )
    assert r.status_code == 201
    assert r.json()["id"] != q_med["id"] and r.json()["medication"] != q_med["medication"]
    assert make.counts(p)["meds"] == 1 and make.counts(q)["meds"] == 1


def test_failure_mid_create_rolls_back__AC19(make, auth, scheduled_body, monkeypatch):
    from fastapi.testclient import TestClient

    from drugtime.main import create_app

    original = SqlMedication.insert_schedules

    def fail_on_second(self, uow, med_id, intake_times, days):
        original(self, uow, med_id, intake_times[:1], days)  # lịch thứ nhất đã ghi
        raise RuntimeError("simulated failure while writing schedule 2")

    monkeypatch.setattr(SqlMedication, "insert_schedules", fail_on_second)
    patient = make.user()
    r = TestClient(create_app(), raise_server_exceptions=False).post(
        "/medications", json=scheduled_body(make.catalog_medication()), headers=auth(patient)
    )
    assert r.status_code == 500
    assert make.counts(patient) == {"meds": 0, "schedules": 0, "prescriptions": 0}


def _open_schedules(db, med_id):
    rows = db.execute(
        text(
            "SELECT to_char(intake_time, 'HH24:MI') AS hhmi FROM medication_schedules "
            "WHERE user_medication_id = :i AND ended_at IS NULL ORDER BY intake_time"
        ),
        {"i": med_id},
    )
    return [r.hhmi for r in rows]


def test_patch_waits_for_concurrent_schedule_change__AC10(
    client, tx, db, make, auth, scheduled_body
):
    """PATCH đổi giờ chạy đua với một thay đổi lịch khác chưa commit.

    Kết nối A giữ khóa dòng thuốc, đã đóng lịch cũ và mở lịch 06:00 nhưng chưa commit. PATCH B
    phải chờ A, rồi thấy và đóng cả lịch 06:00; cuối cùng chỉ còn đúng một bộ lịch mở."""
    patient = make.user()
    med = client.post(
        "/medications", json=scheduled_body(make.catalog_medication()), headers=auth(patient)
    ).json()

    tx.begin()
    tx.execute(text("SELECT id FROM user_medications WHERE id = :i FOR UPDATE"), {"i": med["id"]})
    tx.execute(
        text(
            "UPDATE medication_schedules SET ended_at = now() "
            "WHERE user_medication_id = :i AND ended_at IS NULL"
        ),
        {"i": med["id"]},
    )
    tx.execute(
        text(
            "INSERT INTO medication_schedules (user_medication_id, intake_time, days_of_week) "
            "VALUES (:i, '06:00', ARRAY[1, 2, 3, 4, 5, 6, 7]::smallint[])"
        ),
        {"i": med["id"]},
    )

    t, result = _in_thread(
        lambda: client.patch(
            f"/medications/{med['id']}",
            json={"intake_times": ["09:00", "21:00"]},
            headers=auth(patient),
        )
    )
    _wait_until_blocked(db)
    tx.commit()
    t.join(timeout=15)

    r = result["response"]
    assert r.status_code == 200, r.text
    assert _open_schedules(db, med["id"]) == ["09:00", "21:00"]
    assert [s["intake_time"] for s in r.json()["schedules"]] == ["09:00", "21:00"]


def test_two_parallel_patches_leave_one_schedule_set__AC10(client, db, make, auth, scheduled_body):
    patient = make.user()
    med = client.post(
        "/medications", json=scheduled_body(make.catalog_medication()), headers=auth(patient)
    ).json()
    barrier = threading.Barrier(2)
    sets = (["07:00"], ["10:00", "22:00"])

    def send(times):
        barrier.wait()
        return client.patch(
            f"/medications/{med['id']}", json={"intake_times": times}, headers=auth(patient)
        )

    threads = [_in_thread(lambda times=times: send(times)) for times in sets]
    for t, _ in threads:
        t.join(timeout=15)
    assert all(res["response"].status_code == 200 for _, res in threads)
    assert _open_schedules(db, med["id"]) in [list(x) for x in sets]


def test_patch_started_earlier_but_locked_later_does_not_fail__AC10(
    tx, db, make, auth, scheduled_body
):
    """Request B1 bắt đầu transaction trước nhưng lấy khóa sau B2.

    B2 (giả lập bằng kết nối A) đã đóng lịch cũ và mở lịch mới với effective_from muộn hơn thời
    điểm bắt đầu của B1. Khi B1 đóng lịch của B2, ended_at không được nhỏ hơn effective_from.
    Kỳ vọng theo contract: B1 vẫn trả 200, không phải 5xx."""
    from fastapi.testclient import TestClient

    from drugtime.main import create_app

    client = TestClient(create_app(), raise_server_exceptions=False)
    patient = make.user()
    med = client.post(
        "/medications", json=scheduled_body(make.catalog_medication()), headers=auth(patient)
    ).json()

    tx.begin()
    tx.execute(text("SELECT id FROM user_medications WHERE id = :i FOR UPDATE"), {"i": med["id"]})

    t, result = _in_thread(
        lambda: client.patch(
            f"/medications/{med['id']}",
            json={"intake_times": ["09:00", "21:00"]},
            headers=auth(patient),
        )
    )
    _wait_until_blocked(db)  # B1 đã bắt đầu transaction và đang chờ khóa
    stamp = "clock_timestamp()"  # B2 bắt đầu sau B1 nên mốc của B2 muộn hơn now() của B1
    tx.execute(
        text(
            f"UPDATE medication_schedules SET ended_at = {stamp} "
            "WHERE user_medication_id = :i AND ended_at IS NULL"
        ),
        {"i": med["id"]},
    )
    tx.execute(
        text(
            "INSERT INTO medication_schedules "
            "(user_medication_id, intake_time, days_of_week, effective_from) "
            f"VALUES (:i, '06:00', ARRAY[1, 2, 3, 4, 5, 6, 7]::smallint[], {stamp})"
        ),
        {"i": med["id"]},
    )
    tx.commit()
    t.join(timeout=15)

    r = result["response"]
    assert r.status_code == 200, r.text
    assert _open_schedules(db, med["id"]) == ["09:00", "21:00"]
