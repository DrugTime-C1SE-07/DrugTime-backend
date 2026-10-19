"""Phiên bản quy tắc tương tác (task 2.16): sửa tạo phiên bản mới, phiên bản cũ không đổi, chống ghi
đè đồng thời, lịch sử, no-op. AC18–AC24, AC26."""

import threading

import pytest
from sqlalchemy import text

BASE = "/admin/drug-interactions"
TABLE = "active_ingredient_interactions"


def _body(a, b, **kw):
    return {
        "ingredient_a_id": a,
        "ingredient_b_id": b,
        "interaction_type": "phu_thuoc_lieu",
        "severity_level": 2,
        "handling_type": "can_theo_doi",
        "description": "d",
        "source": "QĐ 5948/QĐ-BYT",
        "dose_thresholds": [
            {
                "ingredient_ref": "A",
                "min_dose": 0,
                "max_dose": 100,
                "dose_unit": "mg/ngày",
                "severity_level": 2,
                "warning_text": "a",
            },
            {
                "ingredient_ref": "B",
                "min_dose": 300,
                "dose_unit": "mg/ngày",
                "severity_level": 4,
                "warning_text": "b",
            },
        ],
        **kw,
    }


@pytest.fixture
def rule(client, admin_auth, make):
    _, h = admin_auth
    r = client.post(BASE, json=_body(make.ingredient(), make.ingredient()), headers=h)
    assert r.status_code == 201, r.text
    return r.json()


def _content(row: dict) -> dict:
    keep = (
        "ingredient_a_id",
        "ingredient_b_id",
        "interaction_type",
        "severity_level",
        "handling_type",
        "min_interval_hours",
        "description",
        "source",
        "created_at",
        "created_by",
    )
    return {k: row[k] for k in keep}


def test_patch_creates_new_version_old_unchanged__AC18(client, admin_auth, make, rule):
    admin_id, h = admin_auth
    before = make.rule_rows(TABLE, rule["id"])[0]
    r = client.patch(
        f"{BASE}/{rule['id']}", json={"expected_version": 1, "severity_level": 3}, headers=h
    )
    assert r.status_code == 200
    v2 = r.json()
    assert (v2["id"], v2["version"], v2["severity_level"]) == (rule["id"], 2, 3)
    assert v2["version_id"] != rule["version_id"]
    assert v2["updated_by"]["id"] == str(admin_id)
    rows = make.rule_rows(TABLE, rule["id"])
    assert [r["version"] for r in rows] == [1, 2]
    assert _content(rows[0]) == _content(before)  # nội dung phiên bản 1 không đổi
    assert rows[0]["superseded_at"] is not None and rows[0]["deleted_at"] is None
    assert rows[1]["superseded_at"] is None and rows[1]["severity_level"] == 3


def test_thresholds_belong_to_each_version__AC19(client, admin_auth, make, rule):
    _, h = admin_auth
    v1_ids = [t["id"] for t in rule["dose_thresholds"]]
    v2 = client.patch(
        f"{BASE}/{rule['id']}", json={"expected_version": 1, "description": "x"}, headers=h
    ).json()
    assert len(v2["dose_thresholds"]) == 2
    assert set(t["id"] for t in v2["dose_thresholds"]).isdisjoint(v1_ids)
    one = [
        {
            "ingredient_ref": "A",
            "min_dose": 10,
            "dose_unit": "mg",
            "severity_level": 3,
            "warning_text": "c",
        }
    ]
    v3 = client.patch(
        f"{BASE}/{rule['id']}", json={"expected_version": 2, "dose_thresholds": one}, headers=h
    ).json()
    assert [t["min_dose"] for t in v3["dose_thresholds"]] == [10]
    assert [t["id"] for t in make.thresholds_of(rule["version_id"])] == v1_ids
    assert len(make.thresholds_of(v2["version_id"])) == 2


def test_stale_expected_version_conflict__AC20(client, admin_auth, make, rule):
    _, h = admin_auth
    client.patch(
        f"{BASE}/{rule['id']}", json={"expected_version": 1, "severity_level": 3}, headers=h
    )
    r = client.patch(
        f"{BASE}/{rule['id']}", json={"expected_version": 1, "source": "khác"}, headers=h
    )
    assert (r.status_code, r.json()) == (409, {"detail": "version_conflict"})
    r = client.delete(f"{BASE}/{rule['id']}", params={"expected_version": 1}, headers=h)
    assert (r.status_code, r.json()) == (409, {"detail": "version_conflict"})
    rows = make.rule_rows(TABLE, rule["id"])
    assert len(rows) == 2 and rows[1]["source"] == rule["source"] and rows[1]["deleted_at"] is None


def test_concurrent_patch_same_version_one_wins__AC20(
    client, admin_auth, admin_engine, make, rule, wait_for_lock_waiters
):
    """Giữ khóa dòng phiên bản 1 để hai PATCH cùng `expected_version = 1` chắc chắn chạy chồng
    nhau; thả khóa: đúng một 200, một 409, và chỉ có hai phiên bản."""
    _, h = admin_auth
    holder = admin_engine.execution_options(isolation_level="READ COMMITTED").connect()
    tx = holder.begin()
    holder.execute(
        text(f"SELECT 1 FROM {TABLE} WHERE rule_id = :r AND version = 1 FOR UPDATE"),
        {"r": rule["id"]},
    )
    results: list[int] = []

    def patch(desc):
        body = {"expected_version": 1, "description": desc}
        results.append(client.patch(f"{BASE}/{rule['id']}", json=body, headers=h).status_code)

    threads = [threading.Thread(target=patch, args=(d,)) for d in ("một", "hai")]
    for t in threads:
        t.start()
    wait_for_lock_waiters(2)
    tx.rollback()
    holder.close()
    for t in threads:
        t.join(timeout=30)
    assert sorted(results) == [200, 409]
    rows = make.rule_rows(TABLE, rule["id"])
    assert [r["version"] for r in rows] == [1, 2]
    assert sum(r["superseded_at"] is None for r in rows) == 1


def test_noop_patch_keeps_version__AC21(client, admin_auth, make, rule):
    _, h = admin_auth
    same = {
        "expected_version": 1,
        "severity_level": 2,
        "description": "d",
        "dose_thresholds": list(reversed(_body(0, 0)["dose_thresholds"])),
    }
    r = client.patch(f"{BASE}/{rule['id']}", json=same, headers=h)
    assert r.status_code == 200 and r.json()["version"] == 1
    assert r.json()["version_id"] == rule["version_id"]
    assert len(make.rule_rows(TABLE, rule["id"])) == 1


def test_history_and_version_lookup_after_delete__AC23(client, admin_auth, rule):
    admin_id, h = admin_auth
    rid = rule["id"]
    client.patch(f"{BASE}/{rid}", json={"expected_version": 1, "severity_level": 3}, headers=h)
    client.patch(f"{BASE}/{rid}", json={"expected_version": 2, "severity_level": 4}, headers=h)
    assert (
        client.delete(f"{BASE}/{rid}", params={"expected_version": 3}, headers=h).status_code == 204
    )
    items = client.get(f"{BASE}/{rid}/versions", headers=h).json()["items"]
    assert [(v["version"], v["state"], v["severity_level"]) for v in items] == [
        (3, "deleted", 4),
        (2, "superseded", 3),
        (1, "superseded", 2),
    ]
    assert items[0]["deleted_by"]["id"] == str(admin_id) and items[0]["deleted_at"]
    assert all(len(v["dose_thresholds"]) == 2 for v in items)
    old = client.get(f"/admin/drug-interaction-versions/{rule['version_id']}", headers=h)
    assert old.status_code == 200
    assert (old.json()["version"], old.json()["severity_level"], old.json()["id"]) == (1, 2, rid)
    missing = client.get("/admin/drug-interaction-versions/2000000000", headers=h)
    assert missing.json() == {"detail": "interaction_version_not_found"}
    missing = client.get(f"{BASE}/2000000000/versions", headers=h)
    assert missing.json() == {"detail": "interaction_rule_not_found"}


def test_recreate_after_delete_is_new_rule__AC24(client, admin_auth, make, rule):
    _, h = admin_auth
    a, b = rule["ingredient_a"]["id"], rule["ingredient_b"]["id"]
    assert client.post(BASE, json=_body(b, a), headers=h).status_code == 409
    client.delete(f"{BASE}/{rule['id']}", params={"expected_version": 1}, headers=h)
    again = client.post(BASE, json=_body(b, a), headers=h).json()
    assert again["id"] != rule["id"] and again["version"] == 1
    assert len(client.get(f"{BASE}/{rule['id']}/versions", headers=h).json()["items"]) == 1


def test_created_at_and_updated_at__AC26(client, admin_auth, rule):
    _, h = admin_auth
    v2 = client.patch(
        f"{BASE}/{rule['id']}", json={"expected_version": 1, "source": "Dược thư"}, headers=h
    ).json()
    assert v2["created_at"] == rule["created_at"]  # thời điểm tạo phiên bản 1
    assert v2["updated_at"] >= rule["updated_at"]
    detail = client.get(f"{BASE}/{rule['id']}", headers=h).json()
    assert (detail["version"], detail["source"], detail["updated_at"]) == (
        2,
        "Dược thư",
        v2["updated_at"],
    )
