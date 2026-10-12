"""API quy tắc tương tác hoạt chất–thực phẩm (task 2.16), Postgres thật. AC10 (theo AC1, AC4, AC5,
AC7, AC8), AC18 cho thực phẩm."""

from uuid import uuid4

from sqlalchemy import text

BASE = "/admin/drug-food-interactions"
TABLE = "drug_food_interactions"


def _body(ingredient_id, food="Nước bưởi chùm", **kw):
    return {
        "ingredient_id": ingredient_id,
        "food_to_avoid": food,
        "severity_level": 3,
        "reason": "Tăng nồng độ thuốc trong máu.",
        "source": "Dược thư Quốc gia Việt Nam 2022",
        **kw,
    }


def test_crud_flow__AC10(client, admin_auth, make, db):
    admin_id, h = admin_auth
    ing = make.ingredient()
    r = client.post(BASE, json=_body(ing), headers=h)
    assert r.status_code == 201, r.text
    created = r.json()
    assert created["ingredient"]["id"] == ing and created["version"] == 1
    assert created["verification_status"] == "da_xac_minh"
    assert client.get(f"{BASE}/{created['id']}", headers=h).json() == created

    r = client.patch(
        f"{BASE}/{created['id']}",
        json={"expected_version": 1, "food_to_avoid": "Rượu", "reason": "r2", "severity_level": 4},
        headers=h,
    )
    assert r.status_code == 200
    assert (r.json()["version"], r.json()["food_to_avoid"], r.json()["severity_level"]) == (
        2,
        "Rượu",
        4,
    )
    rows = make.rule_rows(TABLE, created["id"])
    assert [(x["version"], x["food_to_avoid"]) for x in rows] == [
        (1, "Nước bưởi chùm"),
        (2, "Rượu"),
    ]
    assert rows[0]["superseded_at"] is not None

    r = client.delete(f"{BASE}/{created['id']}", params={"expected_version": 2}, headers=h)
    assert r.status_code == 204
    rows = make.rule_rows(TABLE, created["id"])
    assert rows[1]["deleted_at"] is not None and rows[1]["deleted_by"] == admin_id
    assert client.get(f"{BASE}/{created['id']}", headers=h).json() == {
        "detail": "interaction_rule_not_found"
    }
    history = client.get(f"{BASE}/{created['id']}/versions", headers=h).json()["items"]
    assert [v["state"] for v in history] == ["deleted", "superseded"]
    old = client.get(f"/admin/drug-food-interaction-versions/{created['version_id']}", headers=h)
    assert old.json()["food_to_avoid"] == "Nước bưởi chùm"
    assert client.post(BASE, json=_body(ing), headers=h).status_code == 201  # tạo lại sau xóa


def test_validation_errors_write_nothing__AC10_AC4(client, admin_auth, make, db):
    _, h = admin_auth
    ing = make.ingredient()
    for body in (
        _body(2_000_000_000),
        _body(ing, food="   "),
        _body(ing, severity_level=5),
        {**_body(ing), "verification_status": "da_xac_minh"},
        {k: v for k, v in _body(ing).items() if k != "source"},
    ):
        assert client.post(BASE, json=body, headers=h).status_code == 422
    assert client.post(BASE, json=_body(2_000_000_000), headers=h).json() == {
        "detail": "active_ingredient_not_found"
    }
    count = db.execute(
        text(f"SELECT count(*) FROM {TABLE} WHERE active_ingredient_id = :i"), {"i": ing}
    ).scalar_one()
    assert count == 0


def test_duplicate_food_case_insensitive__AC10_AC5(client, admin_auth, make):
    _, h = admin_auth
    ing = make.ingredient()
    assert client.post(BASE, json=_body(ing, food="Bưởi"), headers=h).status_code == 201
    r = client.post(BASE, json=_body(ing, food="BƯỞI"), headers=h)
    assert (r.status_code, r.json()) == (409, {"detail": "interaction_rule_exists"})
    assert (
        client.post(BASE, json=_body(make.ingredient(), food="Bưởi"), headers=h).status_code == 201
    )


def test_patch_food_to_duplicate_conflict_writes_nothing(client, admin_auth, make):
    _, h = admin_auth
    ing = make.ingredient()
    client.post(BASE, json=_body(ing, food="Sữa"), headers=h)
    other = client.post(BASE, json=_body(ing, food="Rượu"), headers=h).json()
    r = client.patch(
        f"{BASE}/{other['id']}", json={"expected_version": 1, "food_to_avoid": "sữa"}, headers=h
    )
    assert (r.status_code, r.json()) == (409, {"detail": "interaction_rule_exists"})
    rows = make.rule_rows(TABLE, other["id"])
    assert len(rows) == 1 and rows[0]["superseded_at"] is None  # rollback, phiên bản 1 vẫn mở


def test_patch_rejects_ingredient_change_and_stale_version(client, admin_auth, make):
    _, h = admin_auth
    created = client.post(BASE, json=_body(make.ingredient()), headers=h).json()
    r = client.patch(
        f"{BASE}/{created['id']}", json={"expected_version": 1, "ingredient_id": 1}, headers=h
    )
    assert r.status_code == 422 and isinstance(r.json()["detail"], list)
    client.patch(f"{BASE}/{created['id']}", json={"expected_version": 1, "reason": "x"}, headers=h)
    r = client.patch(
        f"{BASE}/{created['id']}", json={"expected_version": 1, "reason": "y"}, headers=h
    )
    assert r.json() == {"detail": "version_conflict"}


def test_filters__AC10_AC8(client, admin_auth, make):
    _, h = admin_auth
    tag = uuid4().hex[:10]
    a = make.ingredient(name=f"Simva-{tag}")
    b = make.ingredient()
    f1 = client.post(BASE, json=_body(a, food=f"Bưởi-{tag}"), headers=h).json()
    f2 = client.post(BASE, json=_body(a, food="Rượu", severity_level=4), headers=h).json()
    f3 = client.post(BASE, json=_body(b, food=f"Sữa-{tag}"), headers=h).json()

    def ids(params):
        page = client.get(BASE, params=params, headers=h).json()
        return [i["id"] for i in page["items"]], page["total"]

    assert ids({"ingredient_id": a}) == ([f2["id"], f1["id"]], 2)
    assert ids({"ingredient_id": a, "severity_level": 4}) == ([f2["id"]], 1)
    assert ids({"q": f"SIMVA-{tag}"}) == ([f2["id"], f1["id"]], 2)
    assert ids({"q": f"sữa-{tag}"}) == ([f3["id"]], 1)
    assert ids({"medication_id": make.medication_with([b])}) == ([f3["id"]], 1)
    assert ids({"ingredient_id": a, "limit": 1, "skip": 1}) == ([f1["id"]], 2)
