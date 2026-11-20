from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest
from sqlalchemy import event, text

from drugtime.shared.db import get_engine

PATH = "/profile/health-setup"
NONE = {"status": "none_known"}


def condition(db):
    return db.execute(
        text(
            "INSERT INTO conditions (name, medical_nature, data_role) "
            "VALUES (:name, 'benh_ly', 'dieu_chinh_thuoc_khac') RETURNING id"
        ),
        {"name": f"Fixture {uuid4()}"},
    ).scalar_one()


def reported(ids=(), names=()):
    return {"status": "reported", "catalog_ids": list(ids), "custom_names": list(names)}


def reported_allergies(db, ids=(), names=()):
    """Snapshot shape of a reported allergy step: catalog_items carries the catalog label of
    every stored id, retired entries included, in catalog_ids order (contract 02)."""
    rows = db.execute(
        text("SELECT id, category, name FROM allergens WHERE id = ANY(:ids)"), {"ids": list(ids)}
    )
    labels = {row.id: {"id": row.id, "category": row.category, "name": row.name} for row in rows}
    return {**reported(ids, names), "catalog_items": [labels[i] for i in ids]}


def snapshot(client, headers):
    response = client.get(PATH, headers=headers)
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    return response.json()


def test_catalog_and_legacy_selection_roundtrip__AC04_AC05_AC06_AC10(client, db, make, auth):
    user = make.user()
    headers = auth(user)
    cid = condition(db)
    link = db.execute(
        text(
            "INSERT INTO user_conditions (user_id, condition_id, stage) "
            "VALUES (:user, :cid, 'Recorded') RETURNING id"
        ),
        {"user": user, "cid": cid},
    ).scalar_one()
    current = snapshot(client, headers)
    assert current["conditions"] == reported([cid])
    assert current["allergies"] == {"status": "unreported"}
    drug, food = make.allergen(category="drug"), make.allergen(category="food")
    catalog_headers = auth(make.user(consents=()))
    allergens = client.get("/allergens", headers=catalog_headers)
    assert allergens.status_code == 200
    ids = [r["id"] for r in allergens.json()["items"]]
    assert {drug, food} <= set(ids)
    catalog = client.get("/conditions?limit=100", headers=catalog_headers)
    assert catalog.status_code == 200
    assert cid in {row["id"] for row in catalog.json()["items"]}
    data = {
        "revision": current["revision"],
        "allergies": reported([food, drug], [" Tôm khác "]),
        "conditions": reported([cid], ["Bệnh nền tự khai"]),
    }
    response = client.put(PATH, headers=headers, json=data)
    assert response.status_code == 200, response.text
    saved = response.json()
    assert saved["allergies"] == reported_allergies(db, sorted([drug, food]), ["Tôm khác"])
    assert saved["conditions"] == data["conditions"]
    assert snapshot(client, headers) == saved
    old = client.get("/profile", headers=headers).json()["conditions"]
    assert [(row["id"], row["stage"]) for row in old] == [(link, "Recorded")]
    response = client.put(
        PATH, headers=headers, json={"revision": saved["revision"], "conditions": NONE}
    )
    assert response.status_code == 200
    assert response.json()["allergies"] == saved["allergies"]
    assert response.json()["conditions"] == NONE
    assert client.get("/profile", headers=headers).json()["conditions"] == []


@pytest.mark.parametrize("kind", ["unknown", "inactive"])
def test_put_unknown_or_inactive_allergen_returns_422_unchanged__AC3(client, db, make, auth, kind):
    user = make.user()
    headers = auth(user)
    active = make.allergen()
    stored = client.put(
        PATH,
        headers=headers,
        json={"revision": snapshot(client, headers)["revision"], "allergies": reported([active])},
    )
    assert stored.status_code == 200, stored.text
    before = snapshot(client, headers)
    bad = f"t_missing_{uuid4().hex[:12]}" if kind == "unknown" else make.allergen(active=False)
    result = client.put(
        PATH,
        headers=headers,
        json={"revision": before["revision"], "allergies": reported([active, bad])},
    )
    assert result.status_code == 422
    assert result.json() == {"detail": "allergen_not_found"}
    after = snapshot(client, headers)
    assert after == before  # same selection and same revision: nothing written
    stored = db.execute(
        text("SELECT allergen_ids FROM health_profile_setup WHERE user_id = :u"), {"u": user}
    ).scalar_one()
    assert stored == [active]


def test_put_allergy_name_over_40_returns_422_unchanged__AC12(client, db, make, auth):
    """Custom allergy names are sent unchanged to meal suggestions (<= 40 chars per item)."""
    user = make.user()
    headers = auth(user)
    before = snapshot(client, headers)
    result = client.put(
        PATH,
        headers=headers,
        json={"revision": before["revision"], "allergies": reported([], ["x" * 41])},
    )
    assert result.status_code == 422
    assert snapshot(client, headers) == before
    rows = db.execute(
        text("SELECT count(*) FROM health_profile_setup WHERE user_id = :u"), {"u": user}
    ).scalar_one()
    assert rows == 0

    exact = client.put(
        PATH,
        headers=headers,
        json={"revision": before["revision"], "allergies": reported([], ["x" * 40])},
    )
    assert exact.status_code == 200, exact.text
    assert exact.json()["allergies"]["custom_names"] == ["x" * 40]


def test_retired_allergen_kept_in_snapshot_and_resubmittable__AC4(client, db, make, auth):
    headers = auth(make.user())
    retiring, other = make.allergen(category="drug"), make.allergen(category="food")
    saved = client.put(
        PATH,
        headers=headers,
        json={
            "revision": snapshot(client, headers)["revision"],
            "allergies": reported([retiring], ["Phấn hoa"]),
        },
    )
    assert saved.status_code == 200, saved.text
    make.set_allergen_active(retiring, False)

    listed = client.get("/allergens", headers=headers)
    assert listed.status_code == 200
    assert retiring not in {row["id"] for row in listed.json()["items"]}

    current = snapshot(client, headers)
    assert current["allergies"] == reported_allergies(db, [retiring], ["Phấn hoa"])
    assert current["allergies"]["catalog_items"][0]["name"] == f"Dị ứng test {retiring}"

    # The app resubmits the stored selection unchanged: accepted, no new revision.
    same = client.put(
        PATH,
        headers=headers,
        json={"revision": current["revision"], "allergies": reported([retiring], ["Phấn hoa"])},
    )
    assert same.status_code == 200, same.text
    assert same.json() == current

    # Keeping the retired id while adding an active one is also accepted.
    grown = client.put(
        PATH,
        headers=headers,
        json={"revision": current["revision"], "allergies": reported([retiring, other])},
    )
    assert grown.status_code == 200, grown.text
    assert grown.json()["allergies"] == reported_allergies(db, sorted([retiring, other]))
    assert grown.json()["revision"] != current["revision"]


@pytest.mark.parametrize(
    "conditions, code",
    [
        (reported(names=[" "]), "invalid_custom_name"),
        (reported(names=["Tôm", " TÔM "]), "duplicate_custom_name"),
        (reported(ids=[9223372036854775807]), "condition_not_found"),
    ],
)
def test_invalid_second_step_leaves_first_unchanged__AC04_AC07(
    client, make, auth, conditions, code
):
    headers = auth(make.user())
    before = snapshot(client, headers)
    result = client.put(
        PATH,
        headers=headers,
        json={
            "revision": before["revision"],
            "allergies": NONE,
            "conditions": conditions,
        },
    )
    assert result.status_code == 422
    assert result.json() == {"detail": code}
    assert snapshot(client, headers) == before


def test_parallel_writes_and_readback_do_not_duplicate_links__AC07(client, db, make, auth):
    headers = auth(make.user())
    cid = condition(db)
    before = snapshot(client, headers)
    body = {"revision": before["revision"], "conditions": reported([cid])}
    barrier = Barrier(2)

    def submit():
        barrier.wait(timeout=10)
        return client.put(PATH, headers=headers, json=body).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        first, second = pool.submit(submit), pool.submit(submit)
        assert sorted([first.result(), second.result()]) == [200, 409]
    after = snapshot(client, headers)
    assert after["conditions"] == reported([cid])
    assert (
        client.put(PATH, headers=headers, json={**body, "revision": after["revision"]}).json()
        == after
    )
    assert len(client.get("/profile", headers=headers).json()["conditions"]) == 1
    link = client.get("/profile", headers=headers).json()["conditions"][0]["id"]
    assert (
        client.patch(
            f"/profile/conditions/{link}", headers=headers, json={"stage": "Updated"}
        ).status_code
        == 200
    )
    assert (
        client.put(PATH, headers=headers, json={**body, "revision": after["revision"]}).status_code
        == 409
    )


@pytest.mark.parametrize("method", ["get", "put"])
def test_revocation_on_next_request_denies_and_audits__AC08(client, db, make, auth, method):
    user = make.user()
    headers = auth(user)
    before = snapshot(client, headers)
    assert make.access_logs(user)[-1]["result"] == "allowed"
    make.revoke_consent(user, "health_data")
    body = {"revision": before["revision"], "allergies": NONE}
    response = client.request(method, PATH, headers=headers, json=body if method == "put" else None)
    assert response.status_code == 403
    assert response.json() == {"detail": "consent_revoked"}
    assert make.access_logs(user)[-1]["result"] == "denied"
    assert (
        db.execute(
            text("SELECT count(*) FROM health_profile_setup WHERE user_id=:u"), {"u": user}
        ).scalar_one()
        == 0
    )


@pytest.mark.parametrize("linked", [False, True])
def test_cross_patient_denied_even_with_active_sharing__AC08(client, make, auth, linked):
    owner = make.user(consents=("health_data", "family_sharing"))
    other = make.user()
    if linked:
        make.link(owner, other, status="active", sharing=True)
    headers = auth(other)
    for method, body in [("get", None), ("put", {"revision": "0", "allergies": NONE})]:
        response = client.request(
            method, PATH, params={"patient_id": str(owner)}, headers=headers, json=body
        )
        assert response.status_code == 403
        assert response.json() == {"detail": "khong_co_quyen"}
    assert [row["result"] for row in make.access_logs(owner)] == ["denied", "denied"]
    assert snapshot(client, headers)["allergies"] == {"status": "unreported"}


@pytest.mark.parametrize(
    "body", [b"{}", b"{", b""], ids=["invalid-schema", "invalid-json", "empty"]
)
def test_cross_patient_invalid_body_audits_denial__AC08(client, db, make, auth, body):
    owner = make.user(consents=("health_data", "family_sharing"))
    other = make.user()
    make.link(owner, other, status="active", sharing=True)

    response = client.put(
        PATH,
        params={"patient_id": str(owner)},
        content=body,
        headers={**auth(other), "Content-Type": "application/json"},
    )

    assert response.status_code == 403
    assert response.json() == {"detail": "khong_co_quyen"}
    assert [row["result"] for row in make.access_logs(owner)] == ["denied"]
    assert not db.execute(
        text("SELECT 1 FROM health_profile_setup WHERE user_id IN (:owner, :other)"),
        {"owner": owner, "other": other},
    ).first()


def test_audit_failure_blocks_read_and_save__AC09(client, db, make, auth):
    user = make.user()
    headers = auth(user)
    before = snapshot(client, headers)
    engine = get_engine()

    def reject_audit(_conn, _cursor, statement, _params, _context, _many):
        if statement.lstrip().upper().startswith("INSERT INTO ACCESS_LOGS"):
            raise RuntimeError("test audit unavailable")

    event.listen(engine, "before_cursor_execute", reject_audit)
    try:
        from fastapi.testclient import TestClient

        from drugtime.main import create_app

        with TestClient(create_app(), raise_server_exceptions=False) as failing:
            assert failing.get(PATH, headers=headers).status_code == 500
            response = failing.put(
                PATH,
                headers=headers,
                json={
                    "revision": before["revision"],
                    "allergies": NONE,
                    "conditions": NONE,
                },
            )
            assert response.status_code == 500
            assert "test audit unavailable" not in response.text
    finally:
        event.remove(engine, "before_cursor_execute", reject_audit)
    assert (
        db.execute(
            text("SELECT count(*) FROM health_profile_setup WHERE user_id=:u"), {"u": user}
        ).scalar_one()
        == 0
    )
    assert snapshot(client, headers) == before


def test_admin_and_unknown_owner_selector_have_denied_audit__AC08(client, make, auth):
    admin = make.user(admin=True)
    response = client.get(PATH, headers=auth(admin))
    assert response.status_code == 403
    assert make.access_logs(admin)[-1]["actor_role"] == "admin"
    assert make.access_logs(admin)[-1]["result"] == "denied"
    patient = make.user()
    response = client.get(PATH, params={"patient_id": str(uuid4())}, headers=auth(patient))
    assert response.status_code == 403
    assert make.access_logs(patient)[-1]["result"] == "denied"


def test_transaction_failure_after_writes_rolls_back_both_steps__AC09(
    client, db, make, auth, monkeypatch
):
    from contextlib import contextmanager

    from fastapi.testclient import TestClient

    from drugtime.main import create_app
    from drugtime.modules.medication.adapters.inbound import health_setup_http

    user = make.user()
    headers = auth(user)
    before = snapshot(client, headers)
    original = health_setup_http.unit_of_work

    @contextmanager
    def unavailable_after_write():
        with original() as transaction:
            yield transaction
            raise RuntimeError("test transaction is unavailable before commit")

    with monkeypatch.context() as patch:
        patch.setattr(health_setup_http, "unit_of_work", unavailable_after_write)
        with TestClient(create_app(), raise_server_exceptions=False) as failing:
            response = failing.put(
                PATH,
                headers=headers,
                json={"revision": before["revision"], "allergies": NONE, "conditions": NONE},
            )
            assert response.status_code == 500
    assert (
        db.execute(
            text("SELECT count(*) FROM health_profile_setup WHERE user_id=:u"), {"u": user}
        ).scalar_one()
        == 0
    )
    assert snapshot(client, headers) == before


# --- Chronic diseases vs physiological states (adhoc-20261119-home-ui-feedback) ---------


def physiological(db):
    return db.execute(
        text(
            "INSERT INTO conditions (name, medical_nature, data_role) "
            "VALUES (:name, 'sinh_ly_binh_thuong', 'dieu_chinh_thuoc_khac') RETURNING id"
        ),
        {"name": f"Sinh lý {uuid4()}"},
    ).scalar_one()


def physiological_reported(ids):
    return {"status": "reported", "catalog_ids": list(ids)}


def save(client, headers, **steps):
    body = {"revision": snapshot(client, headers)["revision"], **steps}
    response = client.put(PATH, headers=headers, json=body)
    assert response.status_code == 200, response.text
    return response.json()


def link(db, user, cid):
    db.execute(
        text("INSERT INTO user_conditions (user_id, condition_id) VALUES (:u, :c)"),
        {"u": user, "c": cid},
    )


def test_profile_and_setup_split_by_category__AC16(client, db, make, auth):
    user = make.user()
    headers = auth(user)
    chronic, pregnant = condition(db), physiological(db)
    link(db, user, chronic)
    link(db, user, pregnant)

    rows = client.get("/profile", headers=headers).json()["conditions"]
    assert {(row["condition_id"], row["category"]) for row in rows} == {
        (chronic, "chronic_disease"),
        (pregnant, "physiological_state"),
    }
    current = snapshot(client, headers)
    assert current["conditions"] == reported([chronic])
    assert current["physiological_states"] == physiological_reported([pregnant])


def test_new_user_physiological_step_is_unreported__AC25(client, make, auth):
    current = snapshot(client, auth(make.user()))
    assert current["physiological_states"] == {"status": "unreported"}


def test_physiological_none_removes_pregnancy_and_keeps_diseases__AC25(client, db, make, auth):
    user = make.user()
    headers = auth(user)
    chronic, pregnant = condition(db), physiological(db)
    saved = save(
        client,
        headers,
        conditions=reported([chronic]),
        physiological_states=physiological_reported([pregnant]),
    )
    assert saved["physiological_states"] == physiological_reported([pregnant])

    cleared = save(client, headers, physiological_states=NONE)
    assert cleared["physiological_states"] == NONE
    assert cleared["conditions"] == reported([chronic])
    assert snapshot(client, headers) == cleared
    linked = (
        db.execute(text("SELECT condition_id FROM user_conditions WHERE user_id = :u"), {"u": user})
        .scalars()
        .all()
    )
    assert linked == [chronic]
    flags = db.execute(
        text(
            "SELECT conditions_none_known, physiological_none_known "
            "FROM health_profile_setup WHERE user_id = :u"
        ),
        {"u": user},
    ).one()
    assert tuple(flags) == (False, True)

    # Reporting a state again clears the explicit "none".
    again = save(client, headers, physiological_states=physiological_reported([pregnant]))
    assert again["physiological_states"] == physiological_reported([pregnant])


def test_condition_none_survives_physiological_change__AC17(client, db, make, auth):
    headers = auth(make.user())
    chronic, nursing, pregnant = condition(db), physiological(db), physiological(db)
    save(client, headers, conditions=NONE)

    # Through health setup.
    after = save(client, headers, physiological_states=physiological_reported([nursing]))
    assert after["conditions"] == NONE
    # Through the per-link endpoint used by the profile screen.
    created = client.post("/profile/conditions", headers=headers, json={"condition_id": pregnant})
    assert created.status_code == 201, created.text
    assert created.json()["category"] == "physiological_state"
    assert snapshot(client, headers)["conditions"] == NONE

    # A chronic disease still clears "none" (unchanged behaviour).
    created = client.post("/profile/conditions", headers=headers, json={"condition_id": chronic})
    assert created.status_code == 201, created.text
    assert created.json()["category"] == "chronic_disease"
    current = snapshot(client, headers)
    assert current["conditions"] == reported([chronic])
    assert current["physiological_states"] == physiological_reported(sorted([nursing, pregnant]))


def test_physiological_none_cleared_by_linking_a_state__AC17_AC25(client, db, make, auth):
    headers = auth(make.user())
    pregnant = physiological(db)
    save(client, headers, conditions=NONE, physiological_states=NONE)
    created = client.post("/profile/conditions", headers=headers, json={"condition_id": pregnant})
    assert created.status_code == 201, created.text
    current = snapshot(client, headers)
    assert current["physiological_states"] == physiological_reported([pregnant])
    assert current["conditions"] == NONE


@pytest.mark.parametrize("step", ["conditions", "physiological_states"])
def test_wrong_category_returns_422_unchanged__AC13(client, db, make, auth, step):
    user = make.user()
    headers = auth(user)
    chronic, pregnant = condition(db), physiological(db)
    before = snapshot(client, headers)
    wrong = reported([pregnant]) if step == "conditions" else physiological_reported([chronic])
    result = client.put(
        PATH,
        headers=headers,
        json={"revision": before["revision"], "allergies": NONE, step: wrong},
    )
    assert result.status_code == 422
    assert result.json() == {"detail": "condition_category_mismatch"}
    assert snapshot(client, headers) == before
    assert not db.execute(
        text("SELECT 1 FROM user_conditions WHERE user_id = :u"), {"u": user}
    ).first()


def test_physiological_step_rejects_custom_names_and_unknown_ids__AC13(client, make, auth):
    headers = auth(make.user())
    before = snapshot(client, headers)
    custom = client.put(
        PATH,
        headers=headers,
        json={
            "revision": before["revision"],
            "physiological_states": {
                "status": "reported",
                "catalog_ids": [],
                "custom_names": ["Mang thai"],
            },
        },
    )
    assert custom.status_code == 422
    unknown = client.put(
        PATH,
        headers=headers,
        json={
            "revision": before["revision"],
            "physiological_states": physiological_reported([9223372036854775807]),
        },
    )
    assert unknown.status_code == 422
    assert unknown.json() == {"detail": "condition_not_found"}
    assert snapshot(client, headers) == before


def test_cross_patient_physiological_save_denied_and_audited__AC18(client, db, make, auth):
    owner = make.user(consents=("health_data", "family_sharing"))
    other = make.user()
    make.link(owner, other, status="active", sharing=True)
    pregnant = physiological(db)
    response = client.put(
        PATH,
        params={"patient_id": str(owner)},
        headers=auth(other),
        json={"revision": "0", "physiological_states": physiological_reported([pregnant])},
    )
    assert response.status_code == 403
    assert response.json() == {"detail": "khong_co_quyen"}
    assert [row["result"] for row in make.access_logs(owner)] == ["denied"]
    assert not db.execute(
        text("SELECT 1 FROM user_conditions WHERE user_id IN (:a, :b)"),
        {"a": owner, "b": other},
    ).first()


def test_revoked_consent_blocks_physiological_save__AC18(client, db, make, auth):
    user = make.user()
    headers = auth(user)
    before = snapshot(client, headers)
    make.revoke_consent(user, "health_data")
    response = client.put(
        PATH,
        headers=headers,
        json={"revision": before["revision"], "physiological_states": NONE},
    )
    assert response.status_code == 403
    assert response.json() == {"detail": "consent_revoked"}
    assert make.access_logs(user)[-1]["result"] == "denied"
    assert not db.execute(
        text("SELECT 1 FROM health_profile_setup WHERE user_id = :u"), {"u": user}
    ).first()
