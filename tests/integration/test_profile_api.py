from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import text


def condition(db):
    return db.execute(
        text(
            "INSERT INTO conditions (name,medical_nature,data_role) "
            "VALUES (:n,'benh_ly','dieu_chinh_thuoc_khac') RETURNING id"
        ),
        {"n": f"Profile test {uuid4()}"},
    ).scalar_one()


def add(client, auth, user, cid, **metadata):
    response = client.post(
        "/profile/conditions", headers=auth(user), json={"condition_id": cid, **metadata}
    )
    assert response.status_code == 201, response.text
    assert response.headers["cache-control"] == "no-store"
    return response.json()


def test_profile_get_put_incomplete_complete__AC01_AC04(client, db, make, auth, monkeypatch):
    from drugtime.modules.medication.adapters.inbound import profile_http

    user = make.user()
    db.execute(text("UPDATE users SET full_name=NULL WHERE id=:u"), {"u": user})
    headers = auth(user)
    response = client.get("/profile", headers=headers)
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == {
        "full_name": None,
        "date_of_birth": None,
        "gender": None,
        "conditions": [],
    }
    link = add(client, auth, user, condition(db), subtype="  supplied  ", stage="old")

    class Clock:
        @staticmethod
        def now(tz):
            return datetime(2026, 10, 13, 18, tzinfo=UTC)

    monkeypatch.setattr(profile_http, "datetime", Clock)
    body = {"full_name": "  Bao  ", "date_of_birth": "2026-10-14", "gender": " MALE "}
    response = client.put("/profile", json=body, headers=headers)
    assert response.status_code == 204 and response.content == b""
    profile = client.get("/profile", headers=headers).json()
    assert profile == {
        "full_name": "Bao",
        "date_of_birth": "2026-10-14",
        "gender": "male",
        "conditions": [link],
    }
    for invalid in ({**body, "full_name": "  "}, {**body, "date_of_birth": "2026-10-15"}):
        assert client.put("/profile", json=invalid, headers=headers).status_code == 422
        assert client.get("/profile", headers=headers).json() == profile


def test_conditions_pagination_no_patient_data__AC05(client, db, make, auth):
    user = make.user(consents=())
    ids = [condition(db), condition(db)]
    headers = auth(user)
    total = db.execute(text("SELECT count(*) FROM conditions")).scalar_one()
    response = client.get("/conditions?limit=1&offset=0", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == total and data["limit"] == 1 and data["offset"] == 0
    assert data["items"] == [
        dict(
            db.execute(text("SELECT id,name FROM conditions ORDER BY id LIMIT 1")).mappings().one()
        )
    ]
    assert client.get(f"/conditions?offset={total}", headers=headers).json()["items"] == []
    assert make.access_logs(user) == []
    assert all(cid > 0 for cid in ids)
    for query in ("limit=0", "limit=101", "offset=-1"):
        assert client.get("/conditions?" + query, headers=headers).status_code == 422


@pytest.mark.parametrize("offset", ["total", "beyond", 2**63, 10**100])
def test_conditions_offset_at_or_beyond_total_returns_empty__AC05_AC16(
    client, db, make, auth, offset
):
    user = make.user(consents=())
    condition(db)
    total = db.execute(text("SELECT count(*) FROM conditions")).scalar_one()
    requested = total if offset == "total" else total + 1 if offset == "beyond" else offset
    response = client.get(f"/conditions?offset={requested}", headers=auth(user))
    assert response.status_code == 200, response.text
    assert response.json() == {"items": [], "total": total, "limit": 20, "offset": requested}
    assert make.access_logs(user) == []


def test_create_missing_duplicate_patch_and_hard_delete__AC06_AC11(client, db, make, auth):
    user, other = make.user(), make.user()
    cid = condition(db)
    missing = db.execute(text("SELECT max(id)+1 FROM conditions")).scalar_one()
    headers = auth(user)
    response = client.post("/profile/conditions", json={"condition_id": missing}, headers=headers)
    assert response.status_code == 422 and response.json()["detail"] == "condition_not_found"
    first = add(client, auth, user, cid, subtype="original", stage="old")
    other_link = add(client, auth, other, cid)
    response = client.post("/profile/conditions", json={"condition_id": cid}, headers=headers)
    assert response.status_code == 409 and response.json()["detail"] == "condition_already_exists"
    path = f"/profile/conditions/{first['id']}"
    response = client.patch(path, json={"subtype": None}, headers=headers)
    assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
    assert response.json() == {**first, "subtype": None}
    for invalid in ({}, {"condition_id": cid}, {"user_id": str(other)}, {"stage": 4}):
        assert client.patch(path, json=invalid, headers=headers).status_code == 422
    before = len(make.access_logs(user))
    response = client.delete(path, headers=headers)
    assert response.status_code == 204 and response.content == b""
    assert (
        db.execute(
            text("SELECT count(*) FROM user_conditions WHERE id=:i"), {"i": first["id"]}
        ).scalar_one()
        == 0
    )
    assert (
        db.execute(text("SELECT count(*) FROM conditions WHERE id=:i"), {"i": cid}).scalar_one()
        == 1
    )
    assert client.get("/profile", headers=auth(other)).json()["conditions"] == [other_link]
    assert client.get("/profile", headers=headers).json()["conditions"] == []
    assert len(make.access_logs(user)) >= before + 2
    assert client.delete(path, headers=headers).status_code == 404
    recreated = add(client, auth, user, cid)
    assert recreated["id"] != first["id"]


def test_concurrent_duplicate_single_link__AC08(
    db, admin_engine, make, auth, wait_for_lock_waiters
):
    from fastapi.testclient import TestClient

    from drugtime.main import create_app

    user, cid = make.user(), condition(db)
    headers = auth(user)

    def request():
        with TestClient(create_app()) as client:
            return client.post("/profile/conditions", json={"condition_id": cid}, headers=headers)

    with admin_engine.execution_options(isolation_level="READ COMMITTED").connect() as blocker:
        tx = blocker.begin()
        blocker.execute(text("LOCK TABLE user_conditions IN SHARE MODE"))
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(request) for _ in range(2)]
            try:
                wait_for_lock_waiters(2)
            finally:
                tx.rollback()
            responses = [future.result(timeout=30) for future in futures]
    assert sorted(r.status_code for r in responses) == [201, 409]
    assert (
        db.execute(
            text("SELECT count(*) FROM user_conditions WHERE user_id=:u AND condition_id=:c"),
            {"u": user, "c": cid},
        ).scalar_one()
        == 1
    )


@pytest.mark.parametrize(
    "method,path,body",
    [
        (
            "put",
            "/profile",
            {
                "full_name": "Bao",
                "date_of_birth": "2000-01-01",
                "gender": "nam",
                "user_id": "other",
            },
        ),
        ("post", "/profile/conditions", {"condition_id": True}),
        ("post", "/profile/conditions", {"condition_id": 9223372036854775808}),
        ("patch", "/profile/conditions/0", {"stage": None}),
        ("delete", "/profile/conditions/9223372036854775808", None),
    ],
)
def test_extra_fields_and_invalid_ids__AC16(client, make, auth, method, path, body):
    user = make.user()
    assert client.request(method, path, json=body, headers=auth(user)).status_code == 422


@pytest.mark.parametrize("operation", ["put", "post", "patch"])
def test_unstorable_nul_text_returns_validation_error__AC16(client, db, make, auth, operation):
    from fastapi.testclient import TestClient

    from drugtime.main import create_app

    user, cid = make.user(), condition(db)
    link = add(client, auth, user, cid, stage="unchanged")
    headers = auth(user)
    before = client.get("/profile", headers=headers).json()
    audit_count = len(make.access_logs(user))
    request = {
        "put": (
            "/profile",
            {"full_name": "Bao\u0000Test", "date_of_birth": "2000-01-01", "gender": "nam"},
        ),
        "post": (
            "/profile/conditions",
            {"condition_id": condition(db), "subtype": "test\u0000value"},
        ),
        "patch": (f"/profile/conditions/{link['id']}", {"stage": "test\u0000value"}),
    }
    path, body = request[operation]
    with TestClient(create_app(), raise_server_exceptions=False) as api:
        response = api.request(operation, path, json=body, headers=headers)
    assert len(make.access_logs(user)) == audit_count
    assert client.get("/profile", headers=headers).json() == before
    assert response.status_code == 422, response.text
