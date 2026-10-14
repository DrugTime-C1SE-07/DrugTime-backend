"""GET /patients/{patient_id}/schedules và phân quyền endpoint lịch (task 2.04: AC12–AC16, AC23;
bộ cross-patient của wf-health-endpoint). Mỗi ca phân quyền kiểm cả response lẫn access_logs."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import text

from drugtime.modules.medication.domain import schedule_cursor

SCOPE = "danh_sach_thuoc"
FIELDS = {
    "id",
    "user_medication_id",
    "medication",
    "quantity_per_dose",
    "doses_per_day",
    "intake_timing",
    "intake_time",
    "days_of_week",
    "reminder_enabled",
    "effective_from",
    "ended_at",
}


def _log(actor, role, result, reason=None):
    return {
        "actor_user_id": actor,
        "actor_role": role,
        "data_scope": SCOPE,
        "result": result,
        "rejection_reason": reason,
    }


def _create(client, auth, make, patient, body):
    r = client.post("/medications", json=body, headers=auth(patient))
    assert r.status_code == 201, r.text
    return r.json()


def _closed_schedule(db, med_id, effective_days_ago, ended_days_ago):
    now = datetime.now(UTC)
    return db.execute(
        text(
            "INSERT INTO medication_schedules (user_medication_id, intake_time, days_of_week, "
            "effective_from, ended_at) VALUES (:m, '06:00', ARRAY[1,2,3,4,5,6,7]::smallint[], "
            ":f, :e) RETURNING id"
        ),
        {
            "m": med_id,
            "f": now - timedelta(days=effective_days_ago),
            "e": now - timedelta(days=ended_days_ago),
        },
    ).scalar_one()


def _get(client, auth, caller, patient, **query):
    return client.get(f"/patients/{patient}/schedules", params=query, headers=auth(caller))


def _all_pages(client, auth, caller, patient, limit):
    ids, cursor, pages = [], None, 0
    while True:
        q = {"limit": limit} | ({} if cursor is None else {"cursor": cursor})
        r = _get(client, auth, caller, patient, **q)
        assert r.status_code == 200, r.text
        pages += 1
        ids += [s["id"] for s in r.json()["items"]]
        cursor = r.json()["next_cursor"]
        if cursor is None:
            return ids, pages


@pytest.fixture
def patient_with_meds(client, db, make, auth, scheduled_body, as_needed_body):
    """P có: X (S1, S2 mở; S0 đóng 10 ngày trước; S9 đóng 40 ngày trước), Y đã ngừng,
    Z đã xoá, W khi cần. Người khác có thuốc riêng."""
    p = make.user()
    x = _create(client, auth, make, p, scheduled_body(make.catalog_medication()))
    s0 = _closed_schedule(db, x["id"], 20, 10)
    s9 = _closed_schedule(db, x["id"], 50, 40)
    y = _create(
        client, auth, make, p, scheduled_body(make.catalog_medication(), intake_times=["09:00"])
    )
    assert (
        client.patch(f"/medications/{y['id']}", json={"stopped": True}, headers=auth(p)).status_code
        == 200
    )
    z = _create(client, auth, make, p, scheduled_body(make.catalog_medication()))
    assert client.delete(f"/medications/{z['id']}", headers=auth(p)).status_code == 204
    _create(client, auth, make, p, as_needed_body(make.catalog_medication()))
    stranger = make.user()
    _create(client, auth, make, stranger, scheduled_body(make.catalog_medication()))
    expected = sorted([*(s["id"] for s in x["schedules"]), s0, *(s["id"] for s in y["schedules"])])
    return {"patient": p, "x": x, "s0": s0, "s9": s9, "y": y, "z": z, "expected": expected}


# --- AC12 -----------------------------------------------------------------------------------


def test_patient_reads_own_schedules__AC12(client, make, auth, patient_with_meds):
    d = patient_with_meds
    client.patch(
        f"/medications/{d['x']['id']}/schedules/{d['x']['schedules'][1]['id']}",
        json={"reminder_enabled": False},
        headers=auth(d["patient"]),
    )
    r = _get(client, auth, d["patient"], d["patient"])
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body) == {"items", "next_cursor"} and body["next_cursor"] is None
    items = body["items"]
    ids = [s["id"] for s in items]
    assert ids == sorted(ids)
    x_now = [
        s["id"]
        for s in client.get(f"/medications/{d['x']['id']}", headers=auth(d["patient"])).json()[
            "schedules"
        ]
    ]
    # S2 vừa được thay bằng lịch tắt nhắc: cả bản cũ (đóng hôm nay) và bản mới đều có
    assert set(ids) == set(d["expected"]) | set(x_now)
    assert d["s9"] not in ids
    by_id = {s["id"]: s for s in items}
    assert all(set(s) == FIELDS for s in items)
    assert by_id[d["s0"]]["ended_at"] is not None
    assert all(by_id[i]["ended_at"] is None for i in x_now)
    assert any(s["reminder_enabled"] is False for s in items)
    assert by_id[x_now[0]]["medication"]["id"] == d["x"]["medication"]["id"]
    assert by_id[x_now[0]]["effective_from"].endswith("+07:00")
    assert make.access_logs(d["patient"]) == []


def test_patient_without_schedules_gets_empty_page__AC12(client, make, auth):
    p = make.user()
    r = _get(client, auth, p, p)
    assert r.status_code == 200 and r.json() == {"items": [], "next_cursor": None}


# --- AC23 -----------------------------------------------------------------------------------


def test_pagination__AC23(client, make, auth, scheduled_body):
    p = make.user()
    _create(
        client,
        auth,
        make,
        p,
        scheduled_body(
            make.catalog_medication(), intake_times=["06:00", "09:00", "12:00", "15:00", "18:00"]
        ),
    )
    full = [s["id"] for s in _get(client, auth, p, p).json()["items"]]
    ids, pages = _all_pages(client, auth, p, p, limit=2)
    assert (pages, ids) == (3, full) and len(full) == 5


@pytest.mark.parametrize("cursor", ["!!!", "abc", "eyJhIjoxfQ"])
def test_bad_cursor_422__AC23(client, make, auth, cursor):
    p = make.user()
    r = _get(client, auth, p, p, cursor=cursor)
    assert r.status_code == 422 and r.json() == {"detail": "invalid_cursor"}


def test_cursor_of_other_patient_422__AC23(client, make, auth):
    p = make.user()
    r = _get(client, auth, p, p, cursor=schedule_cursor.encode(uuid4(), 1))
    assert r.status_code == 422 and r.json() == {"detail": "invalid_cursor"}


@pytest.mark.parametrize("limit", [0, 201])
def test_limit_out_of_range_422__AC23(client, make, auth, limit):
    p = make.user()
    r = _get(client, auth, p, p, limit=limit)
    assert r.status_code == 422 and isinstance(r.json()["detail"], list)


# --- AC13, cross-patient --------------------------------------------------------------------


def test_family_allowed_logged_each_page__AC13(client, make, auth, patient_with_meds):
    d = patient_with_meds
    family = make.family_of(d["patient"])
    ids, pages = _all_pages(client, auth, family, d["patient"], limit=2)
    assert ids == d["expected"]
    assert make.access_logs(d["patient"]) == [_log(family, "family", "allowed")] * pages


def test_admin_denied_logged__AC13(client, make, auth, patient_with_meds):
    d = patient_with_meds
    admin = make.user(admin=True)
    r = _get(client, auth, admin, d["patient"])
    assert r.status_code == 403 and r.json() == {"detail": "khong_co_quyen"}
    assert make.access_logs(d["patient"]) == [_log(admin, "admin", "denied", "khong_co_quyen")]


def test_unlinked_user_denied_logged__AC13(client, make, auth, patient_with_meds):
    d = patient_with_meds
    stranger = make.user()
    r = _get(client, auth, stranger, d["patient"])
    assert r.status_code == 403 and r.json() == {"detail": "khong_co_quyen"}
    assert "items" not in r.text
    assert make.access_logs(d["patient"]) == [
        _log(stranger, "khong_co_quyen", "denied", "khong_co_quyen")
    ]


@pytest.mark.parametrize("missing", ["sharing_off", "family_sharing", "health_data"])
def test_family_missing_consent_or_sharing_off_denied(client, make, auth, scheduled_body, missing):
    p = make.user(consents=() if missing == "health_data" else ("health_data",))
    if missing == "family_sharing":
        family = make.user()
        make.link(p, family)
    else:
        family = make.family_of(p, sharing=missing != "sharing_off")
    r = _get(client, auth, family, p)
    assert r.status_code == 403
    assert [(log["result"], log["rejection_reason"]) for log in make.access_logs(p)] == [
        ("denied", "khong_co_quyen")
    ]


def test_family_swaps_patient_id_denied(client, make, auth, scheduled_body):
    p, other = make.user(), make.user()
    family = make.family_of(p)
    _create(client, auth, make, other, scheduled_body(make.catalog_medication()))
    r = _get(client, auth, family, other)
    assert r.status_code == 403
    assert make.access_logs(other) == [_log(family, "khong_co_quyen", "denied", "khong_co_quyen")]
    assert make.access_logs(p) == []


# --- AC14 -----------------------------------------------------------------------------------


@pytest.mark.parametrize("revoke", ["health_data", "family_sharing", "sharing_off", "link"])
def test_revoke_between_pages_403__AC14(client, db, make, auth, patient_with_meds, revoke):
    d = patient_with_meds
    family = make.family_of(d["patient"])
    first = _get(client, auth, family, d["patient"], limit=2)
    assert first.status_code == 200 and first.json()["next_cursor"]
    if revoke in ("health_data", "family_sharing"):
        make.revoke_consent(d["patient"], revoke)
    else:
        db.execute(
            text(
                "UPDATE caregiver_links SET "
                + (
                    "sharing_enabled = false"
                    if revoke == "sharing_off"
                    else "status = 'revoked', revoked_at = now()"
                )
                + " WHERE patient_user_id = :p AND family_user_id = :f"
            ),
            {"p": d["patient"], "f": family},
        )
    r = _get(client, auth, family, d["patient"], limit=2, cursor=first.json()["next_cursor"])
    assert r.status_code == 403
    assert [log["result"] for log in make.access_logs(d["patient"])] == ["allowed", "denied"]


def test_allowed_log_failure_fails_request(make, auth, patient_with_meds, monkeypatch):
    from fastapi.testclient import TestClient

    from drugtime.main import create_app
    from drugtime.modules.access.adapters.outbound.sql_access_log import SqlAccessLog

    d = patient_with_meds
    family = make.family_of(d["patient"])

    def broken(*_args, **_kwargs):
        raise RuntimeError("access_logs unavailable")

    monkeypatch.setattr(SqlAccessLog, "append_allowed", broken)
    r = TestClient(create_app(), raise_server_exceptions=False).get(
        f"/patients/{d['patient']}/schedules", headers=auth(family)
    )
    assert r.status_code == 500
    assert "intake_time" not in r.text


# --- AC15 -----------------------------------------------------------------------------------


def _writes(med):
    s1 = med["schedules"][0]["id"]
    return [
        ("post", f"/medications/{med['id']}/schedules", {"intake_time": "12:00"}),
        ("patch", f"/medications/{med['id']}/schedules/{s1}", {"reminder_enabled": False}),
        ("delete", f"/medications/{med['id']}/schedules/{s1}", None),
        ("patch", f"/medications/{med['id']}", {"days_of_week": [1]}),
    ]


@pytest.mark.parametrize("who", ["family", "admin", "stranger"])
def test_write_endpoints_denied_for_family_admin_stranger__AC15(
    client, make, auth, scheduled_body, who
):
    p = make.user()
    med = _create(client, auth, make, p, scheduled_body(make.catalog_medication()))
    caller = {
        "family": lambda: make.family_of(p),
        "admin": lambda: make.user(admin=True),
        "stranger": make.user,
    }[who]()
    role = {"family": "family", "admin": "admin", "stranger": "khong_co_quyen"}[who]
    before = make.schedules(med["id"]), make.medication_row(med["id"])
    for method, path, body in _writes(med):
        r = client.request(method, path, json=body, headers=auth(caller))
        assert r.status_code == 403 and r.json() == {"detail": "khong_co_quyen"}, (method, path)
    assert (make.schedules(med["id"]), make.medication_row(med["id"])) == before
    assert make.access_logs(p) == [_log(caller, role, "denied", "khong_co_quyen")] * 4


def test_self_revoked_consent_cannot_write__AC15(client, make, auth, scheduled_body):
    p = make.user()
    med = _create(client, auth, make, p, scheduled_body(make.catalog_medication()))
    make.revoke_consent(p, "health_data")
    before = make.schedules(med["id"]), make.medication_row(med["id"])
    for method, path, body in _writes(med):
        r = client.request(method, path, json=body, headers=auth(p))
        assert r.status_code == 403 and r.json() == {"detail": "consent_revoked"}, (method, path)
    assert (make.schedules(med["id"]), make.medication_row(med["id"])) == before
    assert _get(client, auth, p, p).json() == {"detail": "consent_revoked"}


# --- AC16 -----------------------------------------------------------------------------------


@pytest.mark.parametrize("admin", [False, True])
def test_unknown_patient_403_without_log__AC16(client, db, make, auth, admin):
    caller = make.user(admin=admin)
    ghost = uuid4()
    r = _get(client, auth, caller, ghost)
    assert r.status_code == 403 and r.json() == {"detail": "khong_co_quyen"}
    n = db.execute(
        text("SELECT count(*) FROM access_logs WHERE actor_user_id = :a"), {"a": caller}
    ).scalar_one()
    assert n == 0


def test_unauthenticated_401_and_unknown_medication_404__AC16(client, make, auth, scheduled_body):
    p = make.user()
    med = _create(client, auth, make, p, scheduled_body(make.catalog_medication()))
    s1 = med["schedules"][0]["id"]
    for method, path, body in [
        ("get", f"/patients/{p}/schedules", None),
        ("post", f"/medications/{med['id']}/schedules", {"intake_time": "12:00"}),
        ("patch", f"/medications/{med['id']}/schedules/{s1}", {"reminder_enabled": False}),
        ("delete", f"/medications/{med['id']}/schedules/{s1}", None),
    ]:
        assert client.request(method, path, json=body).status_code == 401
        assert (
            client.request(
                method, path, json=body, headers={"Authorization": "Bearer x"}
            ).status_code
            == 401
        )
    assert client.delete(f"/medications/{med['id']}", headers=auth(p)).status_code == 204
    for method, path, body in _writes(med)[:3]:
        r = client.request(method, path, json=body, headers=auth(p))
        assert r.status_code == 404 and r.json() == {"detail": "user_medication_not_found"}
