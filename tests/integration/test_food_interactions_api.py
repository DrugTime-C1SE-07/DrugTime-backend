"""GET /patients/{patient_id}/food-interactions: nội dung kết quả (task 4.05: AC1–AC4, AC7–AC9,
AC15, AC16, AC18, AC23). Postgres thật; dữ liệu tự dựng, không phụ thuộc seed mock."""

import json
import logging
from uuid import uuid4

import pytest
from sqlalchemy import text

RULES = "/admin/drug-food-interactions"
DISCLAIMER = (
    "Thông tin chỉ mang tính tham khảo. Hãy hỏi bác sĩ hoặc dược sĩ trước khi "
    "thay đổi việc dùng thuốc hay ăn uống."
)
REPORT_KEYS = {"patient_id", "as_of", "status", "medications", "disclaimer"}
MED_KEYS = {"user_medication_id", "medication", "is_active", "status", "ingredients", "warnings"}
WARNING_KEYS = {
    "rule_id",
    "version_id",
    "ingredient",
    "food_to_avoid",
    "severity_level",
    "reason",
    "source",
}


def _rule(client, admin_h, ingredient_id, food, severity, reason="Lý do", source="Nguồn A"):
    r = client.post(
        RULES,
        json={
            "ingredient_id": ingredient_id,
            "food_to_avoid": food,
            "severity_level": severity,
            "reason": reason,
            "source": source,
        },
        headers=admin_h,
    )
    assert r.status_code == 201, r.text
    return r.json()


def _add(client, auth, patient, scheduled_body, medication_id):
    r = client.post("/medications", json=scheduled_body(medication_id), headers=auth(patient))
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _lookup(client, auth, caller, patient, **params):
    return client.get(f"/patients/{patient}/food-interactions", params=params, headers=auth(caller))


def _ok(r):
    assert r.status_code == 200, r.text
    assert r.headers["cache-control"] == "no-store"
    body = r.json()
    assert set(body) == REPORT_KEYS
    assert body["disclaimer"] == DISCLAIMER
    assert body["as_of"].endswith("+07:00")
    return body


def test_patient_sees_rule_with_version__AC1(client, make, auth, admin_auth, scheduled_body):
    _, admin_h = admin_auth
    p = make.user()
    x = make.ingredient(name=f"Metronidazol-{uuid4().hex[:6]}")
    rule = _rule(client, admin_h, x, "Rượu và đồ uống có cồn", 3, "Phản ứng disulfiram", "DTQG")
    um = _add(client, auth, p, scheduled_body, make.medication_with([x]))

    body = _ok(_lookup(client, auth, p, p))
    assert body["patient_id"] == str(p)
    assert body["status"] == "co_tuong_tac"
    [m] = body["medications"]
    assert set(m) == MED_KEYS
    assert (m["user_medication_id"], m["is_active"], m["status"]) == (um, True, "co_tuong_tac")
    assert m["ingredients"] == [{"id": x, "standard_name": rule["ingredient"]["standard_name"]}]
    assert m["warnings"] == [
        {
            "rule_id": rule["id"],
            "version_id": rule["version_id"],
            "ingredient": {"id": x, "standard_name": rule["ingredient"]["standard_name"]},
            "food_to_avoid": "Rượu và đồ uống có cồn",
            "severity_level": 3,
            "reason": "Phản ứng disulfiram",
            "source": "DTQG",
        }
    ]


def test_all_warnings_of_combo_listed_and_sorted__AC2(
    client, make, auth, admin_auth, scheduled_body
):
    _, admin_h = admin_auth
    p = make.user()
    x, y = make.ingredient(), make.ingredient()
    _rule(client, admin_h, x, "Sữa", 2)
    _rule(client, admin_h, x, "Rượu", 4)
    _rule(client, admin_h, y, "Bưởi", 2)
    _add(client, auth, p, scheduled_body, make.medication_with([x, y]))

    [m] = _ok(_lookup(client, auth, p, p))["medications"]
    assert m["status"] == "co_tuong_tac"
    got = [(w["severity_level"], w["food_to_avoid"], w["ingredient"]["id"]) for w in m["warnings"]]
    assert got == [(4, "Rượu", x), (2, "Bưởi", y), (2, "Sữa", x)]
    assert {i["id"] for i in m["ingredients"]} == {x, y}


def test_combo_only_ingredient_with_rule_warned__AC5(
    client, make, auth, admin_auth, scheduled_body
):
    _, admin_h = admin_auth
    p = make.user()
    x, y = make.ingredient(), make.ingredient()
    _rule(client, admin_h, x, "Rượu", 3)
    _add(client, auth, p, scheduled_body, make.medication_with([x, y]))
    [m] = _ok(_lookup(client, auth, p, p))["medications"]
    assert m["status"] == "co_tuong_tac"
    assert [w["ingredient"]["id"] for w in m["warnings"]] == [x]


def test_none_found_when_ingredients_have_no_rules__AC3(client, make, auth, scheduled_body):
    p = make.user()
    x = make.ingredient()
    _add(client, auth, p, scheduled_body, make.medication_with([x]))
    body = _ok(_lookup(client, auth, p, p))
    [m] = body["medications"]
    assert (m["status"], m["warnings"]) == ("da_kiem_tra_khong_thay", [])
    assert [i["id"] for i in m["ingredients"]] == [x]
    assert body["status"] == "da_kiem_tra_khong_thay"


def test_insufficient_without_ingredients_even_with_rules__AC4(
    client, make, auth, admin_auth, scheduled_body
):
    _, admin_h = admin_auth
    _rule(client, admin_h, make.ingredient(), "Rượu", 4)  # bảng quy tắc không rỗng
    p = make.user()
    _add(client, auth, p, scheduled_body, make.catalog_medication(with_ingredient=False))
    body = _ok(_lookup(client, auth, p, p))
    [m] = body["medications"]
    assert (m["status"], m["ingredients"], m["warnings"]) == ("khong_du_du_lieu", [], [])
    assert body["status"] == "khong_du_du_lieu"


def test_overall_status_mixed__AC6(client, make, auth, admin_auth, scheduled_body):
    _, admin_h = admin_auth
    p = make.user()
    x, z = make.ingredient(), make.ingredient()
    _rule(client, admin_h, x, "Rượu", 3)
    a = _add(client, auth, p, scheduled_body, make.medication_with([x]))
    b = _add(client, auth, p, scheduled_body, make.medication_with([z]))
    c = _add(client, auth, p, scheduled_body, make.catalog_medication(with_ingredient=False))
    body = _ok(_lookup(client, auth, p, p))
    assert [(m["user_medication_id"], m["status"]) for m in body["medications"]] == [
        (a, "co_tuong_tac"),
        (b, "da_kiem_tra_khong_thay"),
        (c, "khong_du_du_lieu"),
    ]
    assert body["status"] == "co_tuong_tac"


def test_rule_edit_and_delete_take_effect_next_request__AC7(
    client, make, auth, admin_auth, scheduled_body
):
    _, admin_h = admin_auth
    p = make.user()
    x = make.ingredient()
    rule = _rule(client, admin_h, x, "Rượu", 3)
    _add(client, auth, p, scheduled_body, make.medication_with([x]))
    [w] = _ok(_lookup(client, auth, p, p))["medications"][0]["warnings"]
    assert w["version_id"] == rule["version_id"]

    r = client.patch(
        f"{RULES}/{rule['id']}",
        json={"expected_version": 1, "food_to_avoid": "Bia", "severity_level": 4},
        headers=admin_h,
    )
    assert r.status_code == 200, r.text
    v2 = r.json()
    [w] = _ok(_lookup(client, auth, p, p))["medications"][0]["warnings"]
    assert (w["rule_id"], w["version_id"], w["food_to_avoid"], w["severity_level"]) == (
        rule["id"],
        v2["version_id"],
        "Bia",
        4,
    )
    assert v2["version_id"] != rule["version_id"]

    r = client.delete(f"{RULES}/{rule['id']}", params={"expected_version": 2}, headers=admin_h)
    assert r.status_code == 204
    [m] = _ok(_lookup(client, auth, p, p))["medications"]
    assert (m["status"], m["warnings"]) == ("da_kiem_tra_khong_thay", [])


def test_active_only_and_filter_stopped__AC8(client, make, auth, admin_auth, scheduled_body):
    _, admin_h = admin_auth
    p = make.user()
    x = make.ingredient()
    _rule(client, admin_h, x, "Rượu", 3)
    m1 = _add(client, auth, p, scheduled_body, make.medication_with([x]))
    m2 = _add(client, auth, p, scheduled_body, make.medication_with([x]))
    m3 = _add(client, auth, p, scheduled_body, make.medication_with([x]))
    stop = client.patch(f"/medications/{m2}", json={"stopped": True}, headers=auth(p))
    assert stop.status_code == 200, stop.text
    assert client.delete(f"/medications/{m3}", headers=auth(p)).status_code == 204

    body = _ok(_lookup(client, auth, p, p))
    assert [m["user_medication_id"] for m in body["medications"]] == [m1]

    body = _ok(_lookup(client, auth, p, p, user_medication_id=m2))
    [m] = body["medications"]
    assert (m["user_medication_id"], m["is_active"], m["status"]) == (m2, False, "co_tuong_tac")
    assert body["status"] == "co_tuong_tac"


@pytest.mark.parametrize("case", ["foreign", "deleted", "unknown"])
def test_filter_foreign_deleted_unknown_404__AC9(client, make, auth, scheduled_body, case):
    p, other = make.user(), make.user()
    secret_name = f"Bí mật {uuid4().hex[:8]}"
    if case == "foreign":
        target = _add(
            client, auth, other, scheduled_body, make.catalog_medication(name=secret_name)
        )
    elif case == "deleted":
        target = _add(client, auth, p, scheduled_body, make.catalog_medication(name=secret_name))
        assert client.delete(f"/medications/{target}", headers=auth(p)).status_code == 204
    else:
        target = 2_000_000_000
    r = _lookup(client, auth, p, p, user_medication_id=target)
    assert r.status_code == 404
    assert r.json() == {"detail": "user_medication_not_found"}
    assert secret_name not in r.text


def test_no_medications_insufficient_with_disclaimer__AC15_AC16(client, make, auth):
    p = make.user()
    body = _ok(_lookup(client, auth, p, p))
    assert (body["status"], body["medications"]) == ("khong_du_du_lieu", [])


def test_every_200_variant_has_disclaimer__AC16(client, make, auth, admin_auth, scheduled_body):
    _, admin_h = admin_auth
    p = make.user()
    x, z = make.ingredient(), make.ingredient()
    _rule(client, admin_h, x, "Rượu", 3)
    ids = [
        _add(client, auth, p, scheduled_body, make.medication_with([x])),
        _add(client, auth, p, scheduled_body, make.medication_with([z])),
        _add(client, auth, p, scheduled_body, make.catalog_medication(with_ingredient=False)),
    ]
    seen = {_ok(_lookup(client, auth, p, p))["status"]}
    for um in ids:
        seen.add(_ok(_lookup(client, auth, p, p, user_medication_id=um))["status"])
    assert seen == {"co_tuong_tac", "da_kiem_tra_khong_thay", "khong_du_du_lieu"}


def test_no_internal_fields_and_no_health_data_in_logs__AC18(
    client, make, auth, admin_auth, scheduled_body, caplog
):
    _, admin_h = admin_auth
    p = make.user()
    x = make.ingredient()
    food = f"Thực phẩm riêng tư {uuid4().hex[:8]}"
    med_name = f"Thuốc riêng tư {uuid4().hex[:8]}"
    _rule(client, admin_h, x, food, 3)
    mid = make.medication_with([x])
    make.db.execute(
        text("UPDATE medications SET name = :n WHERE id = :id"), {"n": med_name, "id": mid}
    )
    _add(client, auth, p, scheduled_body, mid)

    caplog.clear()
    with caplog.at_level(logging.DEBUG):
        body = _ok(_lookup(client, auth, p, p))
    [m] = body["medications"]
    assert m["medication"]["name"] == med_name
    assert set(m["medication"]) == {
        "id", "name", "active_ingredient", "strength_text", "dosage_form"
    }
    [w] = m["warnings"]
    assert set(w) == WARNING_KEYS
    raw = json.dumps(body, ensure_ascii=False)
    for internal in ("created_by", "updated_by", "deleted_by", "verification_status", "state"):
        assert f'"{internal}"' not in raw
    assert food not in caplog.text and med_name not in caplog.text


def test_catalog_deleted_medication_still_evaluated__AC23(
    client, db, make, auth, admin_auth, scheduled_body
):
    _, admin_h = admin_auth
    p = make.user()
    x = make.ingredient()
    _rule(client, admin_h, x, "Rượu", 4)
    mid = make.medication_with([x])
    um = _add(client, auth, p, scheduled_body, mid)
    before = make.medication_row(um)
    db.execute(text("UPDATE medications SET deleted_at = now() WHERE id = :id"), {"id": mid})

    [m] = _ok(_lookup(client, auth, p, p))["medications"]
    assert (m["user_medication_id"], m["medication"]["id"], m["status"]) == (
        um,
        mid,
        "co_tuong_tac",
    )
    assert make.medication_row(um) == before
