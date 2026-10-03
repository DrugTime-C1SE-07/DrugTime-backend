"""DELETE /medications/{id} (xoá mềm) và PATCH {"stopped": false} (dùng lại)
(task adhoc-20261002-mobile-medication-api-integration, AC14, AC14b, AC14c, AC14d, contract Q3).

Chạy đua dựng tất định như test_medication_idempotency: kết nối A giữ transaction chưa commit,
request B chạy trong thread; khi thấy B chờ khóa thì A commit.
"""

import threading
import time
from datetime import UTC, datetime

import pytest
from sqlalchemy import text

SCOPE = "danh_sach_thuoc"
UNSTOP = {"stopped": False}


@pytest.fixture
def tx(admin_engine):
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
    raise AssertionError("request never waited on the lock")


def _in_thread(fn):
    result = {}

    def run():
        result["response"] = fn()

    t = threading.Thread(target=run)
    t.start()
    return t, result


def _create(client, auth, patient, body):
    r = client.post("/medications", json=body, headers=auth(patient))
    assert r.status_code == 201, r.text
    return r.json()


def _stop(client, auth, patient, med_id):
    r = client.patch(f"/medications/{med_id}", json={"stopped": True}, headers=auth(patient))
    assert r.status_code == 200, r.text
    return r.json()


def _open(make, med_id):
    return [s for s in make.schedules(med_id) if s["ended_at"] is None]


def _log(actor, role, result, reason=None):
    return {
        "actor_user_id": actor,
        "actor_role": role,
        "data_scope": SCOPE,
        "result": result,
        "rejection_reason": reason,
    }


# --- Dùng lại ------------------------------------------------------------------


def test_reactivate_scheduled_reopens_same_times_days_keeps_history__AC14(
    client, db, make, auth, scheduled_body
):
    patient = make.user()
    med = _create(
        client,
        auth,
        patient,
        scheduled_body(make.catalog_medication(), days_of_week=[1, 2, 3, 4, 5]),
    )
    old_ids = [s["id"] for s in med["schedules"]]
    db.execute(
        text("UPDATE medication_schedules SET reminder_enabled = false WHERE id = :i"),
        {"i": old_ids[1]},
    )
    log_id = make.dose_log(old_ids[0], datetime(2026, 10, 1, 1, 0, tzinfo=UTC), "da_uong")
    stopped = _stop(client, auth, patient, med["id"])
    stopped_at = make.medication_row(med["id"])["ended_at"]

    r = client.patch(f"/medications/{med['id']}", json=UNSTOP, headers=auth(patient))

    assert r.status_code == 200, r.text
    out = r.json()
    assert out["status"] == "active" and out["ended_at"] is None
    assert [
        (s["intake_time"], s["days_of_week"], s["reminder_enabled"]) for s in out["schedules"]
    ] == [
        ("08:00", [1, 2, 3, 4, 5], True),
        ("20:00", [1, 2, 3, 4, 5], False),
    ]
    assert not {s["id"] for s in out["schedules"]} & set(old_ids)
    # Lịch cũ vẫn đóng đúng lúc ngừng; lịch mới mở sau đó.
    rows = {s["id"]: s for s in make.schedules(med["id"])}
    assert all(rows[i]["ended_at"] == stopped_at for i in old_ids)
    assert all(rows[s["id"]]["effective_from"] >= stopped_at for s in out["schedules"])
    # Liều đã ghi vẫn trỏ lịch cũ, không đổi.
    assert [(d["id"], d["medication_schedule_id"]) for d in make.dose_logs_of(med["id"])] == [
        (log_id, old_ids[0])
    ]
    # Phần còn lại giữ nguyên.
    for field in ("quantity_per_dose", "doses_per_day", "intake_timing", "stock_quantity"):
        assert out[field] == stopped[field]
    assert make.access_logs(patient) == []


def test_reactivate_after_time_change_copies_only_last_stop__AC14(
    client, make, auth, scheduled_body
):
    patient = make.user()
    med = _create(client, auth, patient, scheduled_body(make.catalog_medication()))
    r = client.patch(
        f"/medications/{med['id']}", json={"intake_times": ["07:00"]}, headers=auth(patient)
    )
    assert r.status_code == 200
    _stop(client, auth, patient, med["id"])

    out = client.patch(f"/medications/{med['id']}", json=UNSTOP, headers=auth(patient)).json()

    assert [s["intake_time"] for s in out["schedules"]] == ["07:00"]
    assert out["doses_per_day"] == 1


def test_reactivate_as_needed_no_schedules__AC14(client, make, auth, as_needed_body):
    patient = make.user()
    med = _create(client, auth, patient, as_needed_body(make.catalog_medication()))
    _stop(client, auth, patient, med["id"])

    r = client.patch(f"/medications/{med['id']}", json=UNSTOP, headers=auth(patient))

    assert r.status_code == 200
    assert r.json()["status"] == "active" and r.json()["schedules"] == []
    assert make.schedules(med["id"]) == []


def test_unstop_active_is_noop__AC14(client, make, auth, scheduled_body):
    patient = make.user()
    med = _create(client, auth, patient, scheduled_body(make.catalog_medication()))
    before = make.schedules(med["id"])

    r = client.patch(f"/medications/{med['id']}", json=UNSTOP, headers=auth(patient))

    assert r.status_code == 200 and r.json() == med
    assert make.schedules(med["id"]) == before


def test_reactivate_twice_second_is_noop__AC14(client, make, auth, scheduled_body):
    patient = make.user()
    med = _create(client, auth, patient, scheduled_body(make.catalog_medication()))
    _stop(client, auth, patient, med["id"])
    first = client.patch(f"/medications/{med['id']}", json=UNSTOP, headers=auth(patient)).json()
    second = client.patch(f"/medications/{med['id']}", json=UNSTOP, headers=auth(patient)).json()
    assert second == first
    assert len(_open(make, med["id"])) == 2


@pytest.mark.parametrize("extra", [{"stock_quantity": 5}, {"quantity_per_dose": 2}])
def test_unstop_with_other_field_422__AC14(client, make, auth, scheduled_body, extra):
    patient = make.user()
    med = _create(client, auth, patient, scheduled_body(make.catalog_medication()))
    _stop(client, auth, patient, med["id"])
    before = make.medication_row(med["id"])

    r = client.patch(f"/medications/{med['id']}", json={**UNSTOP, **extra}, headers=auth(patient))

    assert r.status_code == 422 and r.json() == {"detail": "medication_rule_violation"}
    assert make.medication_row(med["id"]) == before


def test_reactivate_scheduled_without_matching_schedules_422_writes_nothing(
    client, db, make, auth, scheduled_body
):
    """Dữ liệu cũ: lịch không đóng cùng lúc với lần ngừng → 422, thuốc vẫn đã ngừng."""
    patient = make.user()
    med = _create(client, auth, patient, scheduled_body(make.catalog_medication()))
    _stop(client, auth, patient, med["id"])
    db.execute(
        text(
            "UPDATE medication_schedules SET ended_at = ended_at - interval '1 day', "
            "effective_from = effective_from - interval '2 day' WHERE user_medication_id = :i"
        ),
        {"i": med["id"]},
    )
    before_rows = make.schedules(med["id"])

    r = client.patch(f"/medications/{med['id']}", json=UNSTOP, headers=auth(patient))

    assert r.status_code == 422 and r.json() == {"detail": "medication_rule_violation"}
    assert make.medication_row(med["id"])["ended_at"] is not None
    assert make.schedules(med["id"]) == before_rows


@pytest.mark.parametrize("value", ["false", 0, None])
def test_unstop_non_boolean_422(client, make, auth, scheduled_body, value):
    patient = make.user()
    med = _create(client, auth, patient, scheduled_body(make.catalog_medication()))
    _stop(client, auth, patient, med["id"])
    r = client.patch(f"/medications/{med['id']}", json={"stopped": value}, headers=auth(patient))
    assert r.status_code == 422 and isinstance(r.json()["detail"], list)


# --- Phân quyền ghi ---------------------------------------------------------------


@pytest.mark.parametrize("who", ["family", "admin", "stranger"])
@pytest.mark.parametrize("action", ["reactivate", "delete"])
def test_others_cannot_reactivate_or_delete_denied_logged__AC14b(
    client, make, auth, scheduled_body, who, action
):
    patient = make.user()
    med = _create(client, auth, patient, scheduled_body(make.catalog_medication()))
    _stop(client, auth, patient, med["id"])
    actor = {
        "family": lambda: make.family_of(patient),
        "admin": lambda: make.user(admin=True),
        "stranger": lambda: make.user(),
    }[who]()
    role = {"family": "family", "admin": "admin", "stranger": "khong_co_quyen"}[who]
    before_row, before_sched = make.medication_row(med["id"]), make.schedules(med["id"])

    if action == "reactivate":
        r = client.patch(f"/medications/{med['id']}", json=UNSTOP, headers=auth(actor))
    else:
        r = client.delete(f"/medications/{med['id']}", headers=auth(actor))

    assert r.status_code == 403 and r.json() == {"detail": "khong_co_quyen"}
    assert make.access_logs(patient) == [_log(actor, role, "denied", "khong_co_quyen")]
    assert make.medication_row(med["id"]) == before_row
    assert make.schedules(med["id"]) == before_sched


@pytest.mark.parametrize("action", ["reactivate", "delete"])
def test_self_revoked_consent_then_immediate_write_403(client, make, auth, scheduled_body, action):
    """Kịch bản rút quyền: rút consent health_data rồi gửi ngay → 403, không đổi dữ liệu."""
    patient = make.user()
    med = _create(client, auth, patient, scheduled_body(make.catalog_medication()))
    _stop(client, auth, patient, med["id"])
    before = make.medication_row(med["id"])

    make.revoke_consent(patient, "health_data")
    if action == "reactivate":
        r = client.patch(f"/medications/{med['id']}", json=UNSTOP, headers=auth(patient))
    else:
        r = client.delete(f"/medications/{med['id']}", headers=auth(patient))

    assert r.status_code == 403 and r.json() == {"detail": "consent_revoked"}
    assert make.medication_row(med["id"]) == before


def test_family_link_revoked_then_delete_still_403(client, db, make, auth, scheduled_body):
    patient = make.user()
    med = _create(client, auth, patient, scheduled_body(make.catalog_medication()))
    family = make.family_of(patient)
    db.execute(
        text(
            "UPDATE caregiver_links SET status = 'revoked', revoked_at = now() "
            "WHERE patient_user_id = :p AND family_user_id = :f"
        ),
        {"p": patient, "f": family},
    )
    r = client.delete(f"/medications/{med['id']}", headers=auth(family))
    assert r.status_code == 403
    assert make.access_logs(patient) == [_log(family, "khong_co_quyen", "denied", "khong_co_quyen")]
    assert make.medication_row(med["id"])["deleted_at"] is None


# --- Xoá -----------------------------------------------------------------------------


def test_delete_hides_everywhere_keeps_dose_logs__AC14c(client, make, auth, scheduled_body):
    patient = make.user()
    med = _create(client, auth, patient, scheduled_body(make.catalog_medication()))
    schedule_id = med["schedules"][0]["id"]
    log_id = make.dose_log(schedule_id, datetime(2026, 10, 1, 1, 0, tzinfo=UTC))
    path = f"/medications/{med['id']}"

    r = client.delete(path, headers=auth(patient))

    assert r.status_code == 204 and r.content == b""
    row = make.medication_row(med["id"])
    assert row["deleted_at"] is not None and row["ended_at"] == row["deleted_at"]
    assert _open(make, med["id"]) == []
    assert all(s["ended_at"] == row["deleted_at"] for s in make.schedules(med["id"]))
    assert [d["id"] for d in make.dose_logs_of(med["id"])] == [log_id]

    not_found = {"detail": "user_medication_not_found"}
    assert client.get(path, headers=auth(patient)).json() == not_found
    assert client.get(path, headers=auth(patient)).status_code == 404
    r = client.patch(path, json={"stock_quantity": 1}, headers=auth(patient))
    assert r.status_code == 404 and r.json() == not_found
    assert client.patch(path, json=UNSTOP, headers=auth(patient)).status_code == 404
    assert client.get("/medications", headers=auth(patient)).json() == {"items": []}
    r = client.delete(path, headers=auth(patient))
    assert r.status_code == 404 and r.json() == not_found
    assert make.access_logs(patient) == []


def test_deleted_medication_404_for_family_too(client, make, auth, scheduled_body):
    patient = make.user()
    family = make.family_of(patient)
    med = _create(client, auth, patient, scheduled_body(make.catalog_medication()))
    assert client.delete(f"/medications/{med['id']}", headers=auth(patient)).status_code == 204
    assert client.get(f"/medications/{med['id']}", headers=auth(family)).status_code == 404


def test_delete_already_stopped_keeps_ended_at__AC14c(client, make, auth, scheduled_body):
    patient = make.user()
    med = _create(client, auth, patient, scheduled_body(make.catalog_medication()))
    _stop(client, auth, patient, med["id"])
    ended = make.medication_row(med["id"])["ended_at"]

    assert client.delete(f"/medications/{med['id']}", headers=auth(patient)).status_code == 204

    row = make.medication_row(med["id"])
    assert row["ended_at"] == ended and row["deleted_at"] >= ended


def test_delete_unknown_id_404(client, make, auth):
    r = client.delete("/medications/999999999", headers=auth(make.user()))
    assert r.status_code == 404 and r.json() == {"detail": "user_medication_not_found"}


def test_delete_requires_auth_401(client):
    assert client.delete("/medications/1").status_code == 401


def test_post_replay_of_deleted_404_creates_nothing(client, make, auth, scheduled_body):
    """Contract Q3: gửi lại client_uuid của thuốc đã xoá → 404, không tạo thuốc mới."""
    patient = make.user()
    body = scheduled_body(make.catalog_medication())
    med = _create(client, auth, patient, body)
    assert client.delete(f"/medications/{med['id']}", headers=auth(patient)).status_code == 204
    before = make.counts(patient)

    r = client.post("/medications", json=body, headers=auth(patient))

    assert r.status_code == 404 and r.json() == {"detail": "user_medication_not_found"}
    assert make.counts(patient) == before


def test_deleted_at_requires_ended_at_check(db, make, auth, client, scheduled_body):
    patient = make.user()
    med = _create(client, auth, patient, scheduled_body(make.catalog_medication()))
    from sqlalchemy.exc import IntegrityError

    with pytest.raises(IntegrityError, match="user_medications_deleted_requires_ended"):
        db.execute(
            text("UPDATE user_medications SET deleted_at = now() WHERE id = :i"), {"i": med["id"]}
        )


# --- Chạy đua ------------------------------------------------------------------------


def test_concurrent_delete_and_dose_upsert__AC14d(client, tx, make, auth, scheduled_body):
    """Worker (giả lập bằng kết nối A) đang ghi dose_logs cho lịch của thuốc, chưa commit;
    DELETE chạy cùng lúc. Kỳ vọng: không lỗi FK, cả hai thành công, đúng một dòng liều,
    và không còn lịch mở cho thuốc sau khi xoá."""
    patient = make.user()
    med = _create(client, auth, patient, scheduled_body(make.catalog_medication()))
    schedule_id = med["schedules"][0]["id"]
    at = datetime(2026, 10, 2, 1, 0, tzinfo=UTC)

    tx.begin()
    tx.execute(
        text(
            "INSERT INTO dose_logs (medication_schedule_id, scheduled_at, status) "
            "VALUES (:s, :at, 'bo_lo') ON CONFLICT (medication_schedule_id, scheduled_at) "
            "DO NOTHING"
        ),
        {"s": schedule_id, "at": at},
    )
    t, result = _in_thread(
        lambda: client.delete(f"/medications/{med['id']}", headers=auth(patient))
    )
    t.join(timeout=15)
    assert not t.is_alive(), "DELETE bị chặn bởi ghi dose_logs"
    tx.commit()

    assert result["response"].status_code == 204
    logs = make.dose_logs_of(med["id"])
    assert [(d["medication_schedule_id"], d["status"]) for d in logs] == [(schedule_id, "bo_lo")]
    assert _open(make, med["id"]) == []

    # Ghi lại cùng liều sau khi xoá (Worker chạy lại) vẫn không tạo trùng.
    tx.begin()
    tx.execute(
        text(
            "INSERT INTO dose_logs (medication_schedule_id, scheduled_at, status) "
            "VALUES (:s, :at, 'bo_lo') ON CONFLICT (medication_schedule_id, scheduled_at) "
            "DO NOTHING"
        ),
        {"s": schedule_id, "at": at},
    )
    tx.commit()
    assert len(make.dose_logs_of(med["id"])) == 1


def test_patch_waiting_on_concurrent_delete_gets_404__AC14c(
    client, tx, db, make, auth, scheduled_body
):
    """Kết nối A xoá thuốc (giữ khóa dòng, chưa commit); PATCH đổi giờ chờ khóa rồi phải thấy
    thuốc đã xoá → 404, không mở lịch mới."""
    patient = make.user()
    med = _create(client, auth, patient, scheduled_body(make.catalog_medication()))

    tx.begin()
    tx.execute(text("SELECT id FROM user_medications WHERE id = :i FOR UPDATE"), {"i": med["id"]})
    tx.execute(
        text(
            "UPDATE medication_schedules SET ended_at = clock_timestamp() "
            "WHERE user_medication_id = :i AND ended_at IS NULL"
        ),
        {"i": med["id"]},
    )
    tx.execute(
        text(
            "UPDATE user_medications SET ended_at = clock_timestamp(), "
            "deleted_at = clock_timestamp() WHERE id = :i"
        ),
        {"i": med["id"]},
    )
    t, result = _in_thread(
        lambda: client.patch(
            f"/medications/{med['id']}", json={"intake_times": ["09:00"]}, headers=auth(patient)
        )
    )
    _wait_until_blocked(db)
    tx.commit()
    t.join(timeout=15)

    r = result["response"]
    assert r.status_code == 404 and r.json() == {"detail": "user_medication_not_found"}
    assert _open(make, med["id"]) == []


def test_two_parallel_deletes_one_wins(client, make, auth, scheduled_body):
    patient = make.user()
    med = _create(client, auth, patient, scheduled_body(make.catalog_medication()))
    barrier = threading.Barrier(2)

    def send():
        barrier.wait()
        return client.delete(f"/medications/{med['id']}", headers=auth(patient))

    threads = [_in_thread(send) for _ in range(2)]
    for t, _ in threads:
        t.join(timeout=15)
    codes = sorted(res["response"].status_code for _, res in threads)
    assert codes == [204, 404]
    assert make.medication_row(med["id"])["deleted_at"] is not None
