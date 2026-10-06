"""POST/GET/PATCH /medications với DB thật (task 2.01, AC1–AC13, AC18)."""

import pytest
from sqlalchemy import text


def _med_row(db, med_id):
    return db.execute(
        text(
            "SELECT user_id, prescription_id, entry_method::text AS entry_method, "
            "confirmation_status::text AS confirmation_status, quantity_per_dose, doses_per_day, "
            "dosing_mode::text AS dosing_mode, intake_timing::text AS intake_timing, "
            "stock_quantity, has_interaction_data, client_uuid, ended_at "
            "FROM user_medications WHERE id = :id"
        ),
        {"id": med_id},
    ).one()


def _db_now(db):
    return db.execute(text("SELECT clock_timestamp()")).scalar_one()


CONTRACT_FIELDS = {
    "id",
    "medication",
    "dosing_mode",
    "quantity_per_dose",
    "doses_per_day",
    "intake_timing",
    "stock_quantity",
    "has_interaction_data",
    "status",
    "ended_at",
    "schedules",
}


def _schedules(db, med_id):
    return db.execute(
        text(
            "SELECT id, to_char(intake_time, 'HH24:MI') AS t, days_of_week, effective_from, "
            "ended_at FROM medication_schedules WHERE user_medication_id = :id "
            "ORDER BY id"
        ),
        {"id": med_id},
    ).all()


@pytest.fixture
def patient(make):
    return make.user()


@pytest.fixture
def drug(make):
    return make.catalog_medication()


@pytest.fixture
def create(client, auth):
    def _create(user, body):
        r = client.post("/medications", json=body, headers=auth(user))
        assert r.status_code == 201, r.text
        return r.json()

    return _create


@pytest.fixture
def patch(client, auth):
    def _patch(user, med_id, body):
        return client.patch(f"/medications/{med_id}", json=body, headers=auth(user))

    return _patch


# --- POST ---------------------------------------------------------------------


def test_create_scheduled_medication__AC1(client, db, patient, drug, auth, scheduled_body):
    body = scheduled_body(drug, intake_timing="after_meal", stock_quantity=30)
    before = _db_now(db)
    r = client.post("/medications", json=body, headers=auth(patient))
    after = _db_now(db)
    assert r.status_code == 201, r.text
    out = r.json()
    assert r.headers["Location"] == f"/medications/{out['id']}"
    assert out["medication"]["id"] == drug and out["medication"]["name"].startswith("Test drug")
    assert out["dosing_mode"] == "scheduled" and out["doses_per_day"] == 2
    assert out["intake_timing"] == "after_meal" and out["stock_quantity"] == 30
    assert out["status"] == "active" and out["ended_at"] is None
    assert [s["intake_time"] for s in out["schedules"]] == ["08:00", "20:00"]
    assert all(s["days_of_week"] == [1, 2, 3, 4, 5, 6, 7] for s in out["schedules"])
    assert out["schedules"][0]["effective_from"].endswith("+07:00")

    row = _med_row(db, out["id"])
    assert row.user_id == patient and row.entry_method == "thu_cong"
    assert row.confirmation_status == "da_xac_nhan" and row.doses_per_day == 2
    assert row.dosing_mode == "theo_gio" and row.intake_timing == "sau_an"
    assert row.stock_quantity == 30 and str(row.client_uuid) == body["client_uuid"]
    schedules = _schedules(db, out["id"])
    assert len(schedules) == 2 and all(s.ended_at is None for s in schedules)
    assert len({s.effective_from for s in schedules}) == 1
    assert before <= schedules[0].effective_from <= after


def test_create_as_needed_has_no_schedule__AC2(client, db, patient, drug, as_needed_body, create):
    out = create(patient, as_needed_body(drug, max_doses_per_day=3))
    assert out["dosing_mode"] == "as_needed" and out["doses_per_day"] == 3
    assert out["schedules"] == []
    row = _med_row(db, out["id"])
    assert row.dosing_mode == "khi_can" and row.doses_per_day == 3
    assert _schedules(db, out["id"]) == []


def test_create_without_optional_fields__AC3(client, db, patient, drug, scheduled_body, create):
    out = create(patient, scheduled_body(drug))
    assert out["intake_timing"] is None and out["stock_quantity"] is None
    row = _med_row(db, out["id"])
    assert row.intake_timing is None and row.stock_quantity is None


def test_two_medications_share_default_prescription__AC4(
    client, db, make, patient, drug, scheduled_body, as_needed_body, create
):
    a = create(patient, scheduled_body(drug))
    b = create(patient, as_needed_body(make.catalog_medication()))
    assert _med_row(db, a["id"]).prescription_id == _med_row(db, b["id"]).prescription_id
    rows = db.execute(
        text("SELECT entry_source::text AS s FROM prescriptions WHERE user_id = :u"),
        {"u": patient},
    ).all()
    assert [r.s for r in rows] == ["mac_dinh"]


@pytest.mark.parametrize("body_fixture", ["scheduled_body", "as_needed_body"])
def test_has_interaction_data_follows_catalog__AC5(request, make, patient, body_fixture, create):
    make_body = request.getfixturevalue(body_fixture)
    mapped = create(patient, make_body(make.catalog_medication()))
    unmapped = create(patient, make_body(make.catalog_medication(with_ingredient=False)))
    assert mapped["has_interaction_data"] is True
    assert unmapped["has_interaction_data"] is False


@pytest.mark.parametrize(
    "change",
    [
        {"medication_id": None},
        {"client_uuid": None},
        {"client_uuid": "abc"},
        {"quantity_per_dose": 0},
        {"quantity_per_dose": 11},
        {"intake_times": None},
        {"intake_times": ["08:00", "08:00"]},
        {"intake_times": ["8h"]},
        {"intake_times": ["01:00", "02:00", "03:00", "04:00", "05:00", "06:00", "07:00"]},
        {"days_of_week": []},
        {"days_of_week": [8]},
        {"intake_timing": "with_meal"},
        {"stock_quantity": -1},
        {"stock_quantity": 1.5},
        {"stock_quantity": 10000},
        {"max_doses_per_day": 2},  # scheduled kèm số lần tối đa
        {"dosing_mode": "as_needed"},  # as_needed thiếu số lần tối đa, kèm giờ
        {"dosing_mode": "as_needed", "intake_times": None},  # thiếu số lần tối đa
        {
            "dosing_mode": "as_needed",
            "intake_times": None,
            "max_doses_per_day": 2,
            "days_of_week": [1],
        },  # as_needed kèm ngày trong tuần
        {"dosing_mode": "as_needed", "intake_times": None, "max_doses_per_day": 0},
        {"dosing_mode": "as_needed", "intake_times": None, "max_doses_per_day": 7},
    ],
)
def test_invalid_payload_writes_nothing__AC6(
    client, make, patient, drug, change, auth, scheduled_body
):
    body = {k: v for k, v in {**scheduled_body(drug), **change}.items() if v is not None}
    r = client.post("/medications", json=body, headers=auth(patient))
    assert r.status_code == 422, r.text
    assert make.counts(patient) == {"meds": 0, "schedules": 0, "prescriptions": 0}


@pytest.mark.parametrize("deleted", [False, True])
def test_unknown_or_deleted_catalog_rejected__AC7(
    client, make, patient, deleted, auth, scheduled_body
):
    medication_id = make.catalog_medication(deleted=True) if deleted else 2_000_000_000
    r = client.post("/medications", json=scheduled_body(medication_id), headers=auth(patient))
    assert r.status_code == 422
    assert r.json() == {"detail": "catalog_medication_not_found"}
    assert make.counts(patient) == {"meds": 0, "schedules": 0, "prescriptions": 0}


def test_same_drug_twice_new_client_uuid__AC8(client, make, patient, drug, scheduled_body, create):
    a = create(patient, scheduled_body(drug))
    b = create(patient, scheduled_body(drug))
    assert a["id"] != b["id"]
    assert {s["id"] for s in a["schedules"]}.isdisjoint(s["id"] for s in b["schedules"])
    assert make.counts(patient)["meds"] == 2 and make.counts(patient)["schedules"] == 4


# --- GET ----------------------------------------------------------------------


def test_get_own_medication_returns_contract_fields_only(
    client, patient, drug, auth, scheduled_body, create
):
    out = create(patient, scheduled_body(drug))
    r = client.get(f"/medications/{out['id']}", headers=auth(patient))
    assert r.status_code == 200 and r.json() == out
    # Không lộ user_id, client_uuid, prescription_id hay cột nội bộ khác.
    assert set(out) == CONTRACT_FIELDS
    assert set(out["medication"]) == {
        "id",
        "name",
        "active_ingredient",
        "strength_text",
        "dosage_form",
    }
    assert set(out["schedules"][0]) == {
        "id",
        "intake_time",
        "days_of_week",
        "reminder_enabled",
        "effective_from",
    }


def test_get_shows_soft_deleted_catalog_name(
    client, db, patient, drug, auth, scheduled_body, create
):
    out = create(patient, scheduled_body(drug))
    db.execute(text("UPDATE medications SET deleted_at = now() WHERE id = :m"), {"m": drug})
    r = client.get(f"/medications/{out['id']}", headers=auth(patient))
    assert r.status_code == 200 and r.json()["medication"] == out["medication"]


# --- PATCH --------------------------------------------------------------------


@pytest.mark.parametrize(
    "body, expected",
    [
        ({"quantity_per_dose": 2}, {"quantity_per_dose": 2}),
        ({"quantity_per_dose": 0.5}, {"quantity_per_dose": 0.5}),
        ({"intake_timing": "before_meal"}, {"intake_timing": "before_meal"}),
        ({"intake_timing": None}, {"intake_timing": None}),
        ({"stock_quantity": 12}, {"stock_quantity": 12}),
        ({"stock_quantity": None}, {"stock_quantity": None}),
    ],
)
def test_patch_dose_timing_stock_keeps_schedules__AC9(
    db, patient, drug, body, expected, scheduled_body, create, patch
):
    out = create(patient, scheduled_body(drug, intake_timing="after_meal", stock_quantity=30))
    before = _schedules(db, out["id"])
    r = patch(patient, out["id"], body)
    assert r.status_code == 200, r.text
    assert {k: r.json()[k] for k in expected} == expected
    assert r.json()["schedules"] == out["schedules"]
    assert _schedules(db, out["id"]) == before


def test_patch_times_closes_old_keeps_dose_logs__AC10(
    client, db, patient, drug, scheduled_body, create, patch
):
    out = create(patient, scheduled_body(drug, days_of_week=[5, 1, 3]))
    old_ids = [s["id"] for s in out["schedules"]]
    log_id = db.execute(
        text(
            "INSERT INTO dose_logs (medication_schedule_id, scheduled_at, taken_at, status) "
            "VALUES (:s, now() - interval '1 hour', now(), 'da_uong') RETURNING id"
        ),
        {"s": old_ids[0]},
    ).scalar_one()

    r = patch(patient, out["id"], {"intake_times": ["19:00", "07:00", "12:00"]})
    assert r.status_code == 200, r.text
    new = r.json()
    assert new["doses_per_day"] == 3
    assert [s["intake_time"] for s in new["schedules"]] == ["07:00", "12:00", "19:00"]
    assert all(s["days_of_week"] == [1, 3, 5] for s in new["schedules"])

    rows = {s.id: s for s in _schedules(db, out["id"])}
    assert len(rows) == 5
    closed = [rows[i] for i in old_ids]
    opened = [rows[s["id"]] for s in new["schedules"]]
    request_time = opened[0].effective_from
    assert all(s.ended_at == request_time for s in closed)
    assert all(s.effective_from == request_time and s.ended_at is None for s in opened)
    assert (
        db.execute(
            text("SELECT medication_schedule_id FROM dose_logs WHERE id = :id"), {"id": log_id}
        ).scalar_one()
        == old_ids[0]
    )


def test_switch_scheduled_and_as_needed__AC11(
    client, db, make, patient, drug, scheduled_body, as_needed_body, create, patch
):
    x = create(patient, scheduled_body(drug))
    r = patch(patient, x["id"], {"dosing_mode": "as_needed", "max_doses_per_day": 2})
    assert r.status_code == 200, r.text
    assert r.json()["dosing_mode"] == "as_needed" and r.json()["doses_per_day"] == 2
    assert r.json()["schedules"] == []
    rows = _schedules(db, x["id"])
    assert len(rows) == 2 and all(s.ended_at is not None for s in rows)
    assert _med_row(db, x["id"]).dosing_mode == "khi_can"

    y = create(patient, as_needed_body(make.catalog_medication()))
    before = _db_now(db)
    r = patch(patient, y["id"], {"dosing_mode": "scheduled", "intake_times": ["09:00"]})
    after = _db_now(db)
    assert r.status_code == 200, r.text
    (new_schedule,) = _schedules(db, y["id"])
    assert before <= new_schedule.effective_from <= after
    out = r.json()
    assert out["dosing_mode"] == "scheduled" and out["doses_per_day"] == 1
    assert [(s["intake_time"], s["days_of_week"]) for s in out["schedules"]] == [
        ("09:00", [1, 2, 3, 4, 5, 6, 7])
    ]
    assert _med_row(db, y["id"]).dosing_mode == "theo_gio"

    r = patch(patient, y["id"], {"intake_times": ["10:00", "21:00"]})
    assert r.status_code == 200 and r.json()["doses_per_day"] == 2
    r = patch(patient, x["id"], {"max_doses_per_day": 5})
    assert r.status_code == 200 and r.json()["doses_per_day"] == 5


@pytest.mark.parametrize(
    "body, code",
    [
        ({"intake_times": ["25:00"]}, None),
        ({"intake_times": []}, None),
        ({"intake_times": ["08:00", "08:00"]}, None),
        ({"max_doses_per_day": 0}, None),
        ({"max_doses_per_day": 2}, "medication_rule_violation"),
        ({"dosing_mode": "as_needed"}, "medication_rule_violation"),
        ({"dosing_mode": "as_needed", "intake_times": ["08:00"]}, "medication_rule_violation"),
        ({"stopped": True, "quantity_per_dose": 2}, "medication_rule_violation"),
        ({}, None),
    ],
)
def test_patch_invalid_changes_nothing__AC12(
    client, db, patient, drug, body, code, scheduled_body, create, patch
):
    out = create(patient, scheduled_body(drug))
    before = (_med_row(db, out["id"]), _schedules(db, out["id"]))
    r = patch(patient, out["id"], body)
    assert r.status_code == 422, r.text
    if code:
        assert r.json() == {"detail": code}
    assert (_med_row(db, out["id"]), _schedules(db, out["id"])) == before


def test_stop_is_idempotent_and_freezes__AC13(
    client, db, patient, drug, auth, scheduled_body, create, patch
):
    out = create(patient, scheduled_body(drug))
    r = patch(patient, out["id"], {"stopped": True})
    assert r.status_code == 200, r.text
    stopped = r.json()
    assert stopped["status"] == "stopped" and stopped["ended_at"] and stopped["schedules"] == []
    ended = _med_row(db, out["id"]).ended_at
    assert all(s.ended_at == ended for s in _schedules(db, out["id"]))

    again = patch(patient, out["id"], {"stopped": True})
    assert again.status_code == 200 and again.json() == stopped
    assert _med_row(db, out["id"]).ended_at == ended

    r = patch(patient, out["id"], {"quantity_per_dose": 2})
    assert r.status_code == 422 and r.json() == {"detail": "medication_stopped"}
    r = client.get(f"/medications/{out['id']}", headers=auth(patient))
    assert r.json() == stopped


# --- 401 / 404 ----------------------------------------------------------------


def test_unauthenticated_401_and_unknown_id_404__AC18(
    client, patient, drug, auth, scheduled_body, create, patch
):
    out = create(patient, scheduled_body(drug))
    for headers in ({}, {"Authorization": "Bearer not-a-token"}):
        assert client.get(f"/medications/{out['id']}", headers=headers).status_code == 401
        r = client.patch(f"/medications/{out['id']}", json={"stopped": True}, headers=headers)
        assert r.status_code == 401
        r = client.post("/medications", json=scheduled_body(drug), headers=headers)
        assert r.status_code == 401
    missing = 2_000_000_000
    assert client.get(f"/medications/{missing}").status_code == 401
    r = client.get(f"/medications/{missing}", headers=auth(patient))
    assert r.status_code == 404 and r.json() == {"detail": "user_medication_not_found"}
    r = patch(patient, missing, {"stopped": True})
    assert r.status_code == 404 and r.json() == {"detail": "user_medication_not_found"}


def test_deleted_account_token_401__AC18(client, make, auth, scheduled_body):
    user = make.user()
    make.db.execute(
        text("UPDATE users SET erased_at = now(), email = NULL, full_name = NULL WHERE id = :u"),
        {"u": user},
    )
    # Token đúng chữ ký nhưng tài khoản đã bị xóa.
    r = client.post("/medications", json=scheduled_body(1), headers=auth(user))
    assert r.status_code == 401
