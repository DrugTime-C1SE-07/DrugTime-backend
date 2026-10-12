"""API quy tắc tương tác giữa hai hoạt chất (task 2.16) với Postgres thật, app chạy bằng api_role.

AC1–AC9, AC11, AC15, AC16, AC26, AC27. Mỗi test tạo hoạt chất mới (tên ngẫu nhiên) nên không
đụng dữ liệu test khác.
"""

import threading
from uuid import uuid4

import pytest
from sqlalchemy import text

BASE = "/admin/drug-interactions"


def _body(a: int, b: int | None, **kw) -> dict:
    body = {
        "ingredient_a_id": a,
        "interaction_type": "phu_thuoc_lieu",
        "severity_level": 2,
        "handling_type": "can_theo_doi",
        "description": "Tăng nguy cơ chảy máu.",
        "source": "QĐ 5948/QĐ-BYT",
    }
    if b is not None:
        body["ingredient_b_id"] = b
    return {**body, **kw}


def _threshold(ref="A", lo=0, hi=100, sev=2):
    t = {"ingredient_ref": ref, "dose_unit": "mg/ngày", "severity_level": sev, "warning_text": "w"}
    if lo is not None:
        t["min_dose"] = lo
    if hi is not None:
        t["max_dose"] = hi
    return t


def _counts(db, *ingredient_ids) -> tuple[int, int]:
    """(số phiên bản quy tắc, số ngưỡng) chạm các hoạt chất này."""
    ids = list(ingredient_ids)
    rules = (
        db.execute(
            text(
                "SELECT id FROM active_ingredient_interactions "
                "WHERE ingredient_a_id = ANY(:ids) OR ingredient_b_id = ANY(:ids)"
            ),
            {"ids": ids},
        )
        .scalars()
        .all()
    )
    thresholds = db.execute(
        text(
            "SELECT count(*) FROM active_ingredient_interaction_dose_thresholds "
            "WHERE interaction_id = ANY(:r)"
        ),
        {"r": list(rules)},
    ).scalar_one()
    return len(rules), thresholds


@pytest.fixture
def x(make):
    return make.ingredient()


@pytest.fixture
def y(make):
    return make.ingredient()


def test_create_with_catalog_ingredient_b__AC1(client, admin_auth, db, x, y):
    admin_id, h = admin_auth
    r = client.post(
        BASE,
        json=_body(
            x,
            y,
            interaction_type="chong_chi_dinh",
            severity_level=4,
            handling_type="tranh_phoi_hop",
        ),
        headers=h,
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["version"] == 1 and body["state"] == "current"
    assert body["ingredient_a"]["id"] == x and body["ingredient_b"]["id"] == y
    assert body["ingredient_a"]["standard_name"].startswith("ingredient-")
    assert body["verification_status"] == "da_xac_minh"
    assert body["updated_by"]["id"] == str(admin_id)
    assert body["updated_by"]["email"] == f"{admin_id}@test.local"
    row = db.execute(
        text(
            "SELECT ingredient_b_in_table_a::text AS in_a, verification_status, deleted_at, "
            "created_by FROM active_ingredient_interactions WHERE id = :i"
        ),
        {"i": body["version_id"]},
    ).one()
    assert (row.in_a, row.verification_status, row.deleted_at, row.created_by) == (
        "co",
        "da_xac_minh",
        None,
        admin_id,
    )


def test_create_with_external_ingredient_b__AC2(client, admin_auth, db, x):
    _, h = admin_auth
    r = client.post(BASE, json={**_body(x, None), "ingredient_b_external_name": "Rượu"}, headers=h)
    assert r.status_code == 201, r.text
    assert r.json()["ingredient_b"] is None
    assert r.json()["ingredient_b_external_name"] == "Rượu"
    row = db.execute(
        text(
            "SELECT ingredient_b_id, ingredient_b_external_name, ingredient_b_in_table_a::text "
            "AS in_a FROM active_ingredient_interactions WHERE id = :i"
        ),
        {"i": r.json()["version_id"]},
    ).one()
    assert tuple(row) == (None, "Rượu", "khong")


def test_dose_thresholds_create_replace_keep__AC3(client, admin_auth, x, y):
    _, h = admin_auth
    two = [_threshold("A", 0, 100, 2), _threshold("B", 300, None, 4)]
    created = client.post(BASE, json=_body(x, y, dose_thresholds=two), headers=h).json()
    rid = created["id"]
    detail = client.get(f"{BASE}/{rid}", headers=h).json()
    assert [
        (t["ingredient_ref"], t["min_dose"], t["max_dose"]) for t in detail["dose_thresholds"]
    ] == [
        ("A", 0, 100),
        ("B", 300, None),
    ]
    one = client.patch(
        f"{BASE}/{rid}",
        json={"expected_version": 1, "dose_thresholds": [_threshold("A", 50, 60, 3)]},
        headers=h,
    )
    assert [(t["min_dose"], t["max_dose"]) for t in one.json()["dose_thresholds"]] == [(50, 60)]
    kept = client.patch(
        f"{BASE}/{rid}", json={"expected_version": 2, "description": "khác"}, headers=h
    )
    assert [(t["min_dose"], t["max_dose"]) for t in kept.json()["dose_thresholds"]] == [(50, 60)]


@pytest.mark.parametrize(
    "change, status, detail",
    [
        ({"ingredient_b_id": "SAME"}, 422, "same_ingredient"),
        ({"ingredient_b_id": 2_000_000_000}, 422, "active_ingredient_not_found"),
        ({"ingredient_b_external_name": "Rượu"}, 422, None),  # gửi cả hai B
        ({"severity_level": 0}, 422, None),
        ({"severity_level": 5}, 422, None),
        ({"min_interval_hours": 0}, 422, None),
        ({"handling_type": "doi_gio"}, 422, None),
        ({"dose_thresholds": [_threshold(lo=100, hi=50)]}, 422, "threshold_range_invalid"),
        ({"dose_thresholds": [_threshold(lo=None, hi=None)]}, 422, None),
        ({"interaction_type": "chong_chi_dinh"}, 422, "contraindication_severity_mismatch"),
        (
            {
                "interaction_type": "chong_chi_dinh",
                "severity_level": 4,
                "dose_thresholds": [_threshold()],
            },
            422,
            "threshold_not_allowed",
        ),
        ({"min_interval_hours": 2}, 422, "min_interval_not_allowed"),
    ],
)
def test_validation_errors_write_nothing__AC4(client, admin_auth, db, x, y, change, status, detail):
    _, h = admin_auth
    if change.get("ingredient_b_id") == "SAME":
        change = {"ingredient_b_id": x}
    before = _counts(db, x, y)
    r = client.post(BASE, json=_body(x, y, **change), headers=h)
    assert r.status_code == status, r.text
    if detail is None:
        assert isinstance(r.json()["detail"], list)  # ValidationError
    else:
        assert r.json() == {"detail": detail}
    assert _counts(db, x, y) == before


def test_threshold_for_external_b_rejected__AC4(client, admin_auth, db, x):
    _, h = admin_auth
    body = {
        **_body(x, None),
        "ingredient_b_external_name": "Rượu",
        "dose_thresholds": [_threshold("B")],
    }
    r = client.post(BASE, json=body, headers=h)
    assert r.json() == {"detail": "threshold_ref_invalid"}
    assert _counts(db, x) == (0, 0)


def test_duplicate_pair_conflict__AC5(client, admin_auth, db, x, y):
    _, h = admin_auth
    assert client.post(BASE, json=_body(x, y), headers=h).status_code == 201
    r = client.post(BASE, json=_body(y, x), headers=h)
    assert (r.status_code, r.json()) == (409, {"detail": "interaction_rule_exists"})
    ext = {**_body(x, None), "ingredient_b_external_name": "Rượu"}
    assert client.post(BASE, json=ext, headers=h).status_code == 201
    r = client.post(BASE, json={**ext, "ingredient_b_external_name": "rượu"}, headers=h)
    assert r.json() == {"detail": "interaction_rule_exists"}
    assert _counts(db, x, y)[0] == 2


def test_concurrent_create_one_wins__AC6(
    client, admin_auth, admin_engine, db, x, y, wait_for_lock_waiters
):
    """Một giao dịch giữ cặp (X, Y) chưa commit; hai request tạo (X, Y) và (Y, X) phải chờ index
    unique. Rollback giao dịch đó rồi xem: đúng một request thắng, request kia 409."""
    _, h = admin_auth
    holder = admin_engine.execution_options(isolation_level="READ COMMITTED").connect()
    tx = holder.begin()
    holder.execute(
        text(
            "INSERT INTO active_ingredient_interactions (ingredient_a_id, ingredient_b_id, "
            "ingredient_b_in_table_a, interaction_type, severity_level, handling_type, "
            "description, source, verification_status) VALUES (:a, :b, 'co', 'phu_thuoc_lieu', "
            "2, 'can_theo_doi', 'holder', 's', 'da_xac_minh')"
        ),
        {"a": x, "b": y},
    )
    results: list[int] = []
    threads = [
        threading.Thread(
            target=lambda b=b: results.append(client.post(BASE, json=b, headers=h).status_code)
        )
        for b in (_body(x, y), _body(y, x))
    ]
    for t in threads:
        t.start()
    wait_for_lock_waiters(2)
    tx.rollback()
    holder.close()
    for t in threads:
        t.join(timeout=30)
    assert sorted(results) == [201, 409]
    assert (
        db.execute(
            text(
                "SELECT count(*) FROM active_ingredient_interactions WHERE deleted_at IS NULL "
                "AND superseded_at IS NULL "
                "AND LEAST(ingredient_a_id, ingredient_b_id) = LEAST(:a, :b) "
                "AND GREATEST(ingredient_a_id, ingredient_b_id) = GREATEST(:a, :b)"
            ),
            {"a": x, "b": y},
        ).scalar_one()
        == 1
    )


def test_soft_delete_hides_keeps_rows_and_allows_recreate__AC7(client, admin_auth, db, make, x, y):
    admin_id, h = admin_auth
    created = client.post(BASE, json=_body(x, y, dose_thresholds=[_threshold()]), headers=h).json()
    rid = created["id"]
    r = client.delete(f"{BASE}/{rid}", params={"expected_version": 1}, headers=h)
    assert (r.status_code, r.content) == (204, b"")
    rows = make.rule_rows("active_ingredient_interactions", rid)
    assert (
        len(rows) == 1 and rows[0]["deleted_at"] is not None and rows[0]["deleted_by"] == admin_id
    )
    assert len(make.thresholds_of(rows[0]["id"])) == 1
    for method, url, kw in (
        ("get", f"{BASE}/{rid}", {}),
        ("patch", f"{BASE}/{rid}", {"json": {"expected_version": 1, "severity_level": 3}}),
        ("delete", f"{BASE}/{rid}", {"params": {"expected_version": 1}}),
    ):
        r = client.request(method, url, headers=h, **kw)
        assert (r.status_code, r.json()) == (404, {"detail": "interaction_rule_not_found"})
    listed = client.get(BASE, params={"ingredient_id": x}, headers=h).json()
    assert listed == {"items": [], "total": 0}
    again = client.post(BASE, json=_body(x, y), headers=h)
    assert again.status_code == 201 and again.json()["id"] != rid


def test_list_filters_paging_total_order__AC8_AC26(client, admin_auth, make):
    _, h = admin_auth
    tag = uuid4().hex[:10]
    a = make.ingredient(name=f"Alpha-{tag}")
    b, c, d = make.ingredient(), make.ingredient(), make.ingredient()
    r1 = client.post(BASE, json=_body(a, b), headers=h).json()
    r2 = client.post(BASE, json=_body(c, a, severity_level=3), headers=h).json()  # a ở vị trí B
    r3 = client.post(
        BASE,
        json=_body(
            a,
            d,
            interaction_type="chong_chi_dinh",
            severity_level=4,
            handling_type="tranh_phoi_hop",
        ),
        headers=h,
    ).json()
    ext = client.post(
        BASE, json={**_body(c, None), "ingredient_b_external_name": f"Rượu-{tag}"}, headers=h
    ).json()

    def ids(params):
        page = client.get(BASE, params=params, headers=h).json()
        return [i["id"] for i in page["items"]], page["total"]

    newest_first = [r3["id"], r2["id"], r1["id"]]
    assert ids({"ingredient_id": a}) == (newest_first, 3)
    assert ids({"ingredient_id": a, "severity_level": 3}) == ([r2["id"]], 1)
    assert ids({"ingredient_id": a, "interaction_type": "chong_chi_dinh"}) == ([r3["id"]], 1)
    assert ids({"ingredient_id": a, "limit": 2}) == (newest_first[:2], 3)
    assert ids({"ingredient_id": a, "limit": 2, "skip": 2}) == (newest_first[2:], 3)
    assert ids({"q": f"alpha-{tag.upper()}"}) == (newest_first, 3)  # không phân biệt hoa thường
    assert ids({"q": f"rượu-{tag}"}) == ([ext["id"]], 1)
    med = make.medication_with([b, d])  # thuốc phối hợp hai hoạt chất
    assert ids({"medication_id": med}) == ([r3["id"], r1["id"]], 2)
    assert ids({"medication_id": make.medication_with([])}) == ([], 0)
    item = client.get(BASE, params={"ingredient_id": b}, headers=h).json()["items"][0]
    assert {"version", "created_at", "updated_at", "updated_by", "source"} <= set(item)


def test_patch_content_and_reject_pair_change__AC9(client, admin_auth, x, y):
    _, h = admin_auth
    created = client.post(BASE, json=_body(x, y, dose_thresholds=[_threshold()]), headers=h).json()
    rid = created["id"]
    r = client.patch(
        f"{BASE}/{rid}",
        json={"expected_version": 1, "severity_level": 3, "description": "mới"},
        headers=h,
    )
    body = r.json()
    assert (r.status_code, body["severity_level"], body["description"]) == (200, 3, "mới")
    for field in ("source", "interaction_type", "handling_type", "ingredient_a", "ingredient_b"):
        assert body[field] == created[field]
    for change in (
        {"ingredient_a_id": y},
        {"ingredient_b_id": x},
        {"ingredient_b_external_name": "R"},
    ):
        r = client.patch(f"{BASE}/{rid}", json={"expected_version": 2, **change}, headers=h)
        assert r.status_code == 422 and isinstance(r.json()["detail"], list)
    r = client.patch(
        f"{BASE}/{rid}",
        json={"expected_version": 2, "interaction_type": "chong_chi_dinh", "severity_level": 4},
        headers=h,
    )
    assert r.json() == {"detail": "threshold_not_allowed"}
    r = client.patch(
        f"{BASE}/{rid}",
        json={
            "expected_version": 2,
            "interaction_type": "chong_chi_dinh",
            "severity_level": 4,
            "dose_thresholds": [],
        },
        headers=h,
    )
    assert r.status_code == 200 and r.json()["dose_thresholds"] == []


ROUTES = [
    ("post", BASE, {"json": {}}),
    ("get", BASE, {}),
    ("get", f"{BASE}/1", {}),
    ("patch", f"{BASE}/1", {"json": {"expected_version": 1, "severity_level": 3}}),
    ("delete", f"{BASE}/1", {"params": {"expected_version": 1}}),
    ("get", f"{BASE}/1/versions", {}),
    ("get", "/admin/drug-interaction-versions/1", {}),
    ("get", "/admin/drug-food-interactions", {}),
    ("get", "/admin/active-ingredients", {}),
]


@pytest.mark.parametrize("method, url, kw", ROUTES)
def test_auth_401_and_non_admin_403__AC11(client, auth, make, db, method, url, kw):
    """Cặp được phép/bị từ chối: admin thấy 2xx/4xx nghiệp vụ ở test khác; ở đây user thường 403
    `admin_only`, không token 401. Danh mục không phải dữ liệu sức khỏe: không ghi access_logs."""
    logs_before = db.execute(text("SELECT count(*) FROM access_logs")).scalar_one()
    assert client.request(method, url, **kw).status_code == 401
    user = make.user()
    r = client.request(method, url, headers=auth(user), **kw)
    assert (r.status_code, r.json()) == (403, {"detail": "admin_only"})
    assert db.execute(text("SELECT count(*) FROM access_logs")).scalar_one() == logs_before


def test_non_admin_write_changes_nothing__AC11(client, auth, make, db, x, y):
    r = client.post(BASE, json=_body(x, y), headers=auth(make.user()))
    assert r.status_code == 403
    assert _counts(db, x, y) == (0, 0)


def test_verification_status_not_writable__AC15_AC16(client, admin_auth, db, x, y):
    _, h = admin_auth
    r = client.post(BASE, json=_body(x, y, verification_status="cho_duyet"), headers=h)
    assert r.status_code == 422
    rid = client.post(BASE, json=_body(x, y), headers=h).json()["id"]
    r = client.patch(
        f"{BASE}/{rid}", json={"expected_version": 1, "verification_status": "x"}, headers=h
    )
    assert r.status_code == 422
    statuses = (
        db.execute(
            text(
                "SELECT verification_status FROM active_ingredient_interactions WHERE rule_id = :r"
            ),
            {"r": rid},
        )
        .scalars()
        .all()
    )
    assert statuses == ["da_xac_minh"]


def test_min_interval_rules__AC27(client, admin_auth, db, make):
    _, h = admin_auth
    a, b, c = make.ingredient(), make.ingredient(), make.ingredient()
    with_hours = client.post(
        BASE, json=_body(a, b, handling_type="cach_gio", min_interval_hours=2), headers=h
    )
    assert with_hours.status_code == 201 and with_hours.json()["min_interval_hours"] == 2
    no_hours = client.post(BASE, json=_body(a, c, handling_type="cach_gio"), headers=h)
    assert no_hours.status_code == 201 and no_hours.json()["min_interval_hours"] is None
    for handling in ("tranh_phoi_hop", "can_theo_doi", "giam_lieu"):
        d = make.ingredient()
        r = client.post(
            BASE, json=_body(a, d, handling_type=handling, min_interval_hours=2), headers=h
        )
        assert r.json() == {"detail": "min_interval_not_allowed"}
        assert _counts(db, d) == (0, 0)
    rid = with_hours.json()["id"]
    r = client.patch(
        f"{BASE}/{rid}", json={"expected_version": 1, "handling_type": "can_theo_doi"}, headers=h
    )
    assert r.json() == {"detail": "min_interval_not_allowed"}
    r = client.patch(
        f"{BASE}/{rid}",
        json={"expected_version": 1, "handling_type": "can_theo_doi", "min_interval_hours": None},
        headers=h,
    )
    assert r.status_code == 200 and r.json()["min_interval_hours"] is None


@pytest.mark.parametrize(
    "field, value, ok",
    [
        ("severity_level", 0, False),
        ("severity_level", 1, True),
        ("severity_level", 4, "contraindication"),  # mức 4 hợp lệ (dùng chong_chi_dinh)
        ("severity_level", 5, False),
        ("min_interval_hours", 0, False),
        ("min_interval_hours", 0.5, True),
        ("min_interval_hours", 168, True),
        ("min_interval_hours", 169, False),
        ("description", "a" * 4000, True),
        ("description", "a" * 4001, False),
        ("source", "s" * 500, True),
        ("source", "s" * 501, False),
        ("dose_thresholds", 20, True),
        ("dose_thresholds", 21, False),
    ],
)
def test_create_boundaries(client, admin_auth, make, field, value, ok):
    """Giá trị biên theo contract (min-1, min, max, max+1)."""
    _, h = admin_auth
    body = _body(make.ingredient(), make.ingredient())
    if field == "min_interval_hours":
        body["handling_type"] = "cach_gio"
    if ok == "contraindication":
        body.update(interaction_type="chong_chi_dinh", handling_type="tranh_phoi_hop")
    if field == "dose_thresholds":
        value = [_threshold("A", i, i + 1) for i in range(value)]
    body[field] = value
    r = client.post(BASE, json=body, headers=h)
    assert r.status_code == (201 if ok else 422), r.text
    if ok and field == "dose_thresholds":
        assert len(r.json()["dose_thresholds"]) == len(value)


@pytest.mark.parametrize("limit, status", [(0, 422), (1, 200), (100, 200), (101, 422)])
def test_list_limit_boundaries(client, admin_auth, limit, status):
    _, h = admin_auth
    r = client.get(BASE, params={"limit": limit, "ingredient_id": 2_000_000_000}, headers=h)
    assert r.status_code == status
