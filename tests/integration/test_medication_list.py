"""GET /medications (task adhoc-20261002-mobile-medication-api-integration, AC1–AC4, AC5b).

Danh sách chỉ của chính người gọi: không nhận patient_id, chính chủ không ghi access_logs
(quy tắc có sẵn của access), thiếu consent health_data → 403.
"""


def _add(client, auth, patient, body):
    r = client.post("/medications", json=body, headers=auth(patient))
    assert r.status_code == 201, r.text
    return r.json()


def test_lists_only_own_non_deleted_newest_first__AC1(
    client, make, auth, scheduled_body, as_needed_body
):
    patient, other = make.user(), make.user()
    drug = make.catalog_medication()
    a = _add(client, auth, patient, scheduled_body(drug))
    b = _add(client, auth, patient, as_needed_body(drug))
    stopped = _add(client, auth, patient, scheduled_body(drug))
    deleted = _add(client, auth, patient, scheduled_body(drug))
    _add(client, auth, other, scheduled_body(drug))
    assert (
        client.patch(
            f"/medications/{stopped['id']}", json={"stopped": True}, headers=auth(patient)
        ).status_code
        == 200
    )
    assert client.delete(f"/medications/{deleted['id']}", headers=auth(patient)).status_code == 204

    r = client.get("/medications", headers=auth(patient))

    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"items"}
    items = body["items"]
    assert [m["id"] for m in items] == [stopped["id"], b["id"], a["id"]]
    by_id = {m["id"]: m for m in items}
    assert by_id[stopped["id"]]["status"] == "stopped" and by_id[stopped["id"]]["schedules"] == []
    assert [s["intake_time"] for s in by_id[a["id"]]["schedules"]] == ["08:00", "20:00"]
    assert by_id[b["id"]]["schedules"] == []
    # Mỗi phần tử giống hệt GET /medications/{id}.
    for m in items:
        assert client.get(f"/medications/{m['id']}", headers=auth(patient)).json() == m


def test_empty_list__AC2(client, make, auth):
    patient = make.user()
    r = client.get("/medications", headers=auth(patient))
    assert r.status_code == 200 and r.json() == {"items": []}


def test_requires_auth_401__AC3(client):
    assert client.get("/medications").status_code == 401
    r = client.get("/medications", headers={"Authorization": "Bearer not-a-token"})
    assert r.status_code == 401


def test_self_list_writes_no_access_log__AC4(client, make, auth, scheduled_body):
    patient = make.user()
    _add(client, auth, patient, scheduled_body(make.catalog_medication()))
    assert client.get("/medications", headers=auth(patient)).status_code == 200
    assert make.access_logs(patient) == []


def test_self_revoked_consent_403_immediately__AC4(client, make, auth, scheduled_body):
    """Kịch bản rút consent: request ngay sau khi rút bị từ chối, không trả dữ liệu."""
    patient = make.user()
    _add(client, auth, patient, scheduled_body(make.catalog_medication()))
    assert client.get("/medications", headers=auth(patient)).status_code == 200

    make.revoke_consent(patient, "health_data")
    r = client.get("/medications", headers=auth(patient))

    assert r.status_code == 403 and r.json() == {"detail": "consent_revoked"}
    assert "items" not in r.text


def test_linked_family_sees_only_own_list(client, make, auth, scheduled_body):
    """Cross-patient: người thân có link + consent hợp lệ với P gọi GET /medications chỉ thấy
    thuốc của chính mình; endpoint không có cách nào chọn patient khác."""
    patient = make.user()
    family = make.family_of(patient)
    _add(client, auth, patient, scheduled_body(make.catalog_medication()))

    r = client.get("/medications", headers=auth(family))
    assert r.status_code == 200 and r.json() == {"items": []}
    # patient_id gửi kèm bị bỏ qua, không đổi phạm vi.
    r = client.get(f"/medications?patient_id={patient}", headers=auth(family))
    assert r.status_code == 200 and r.json() == {"items": []}
    assert make.access_logs(patient) == []


def test_items_include_active_ingredient__AC5b(client, make, auth, scheduled_body):
    patient = make.user()
    with_text = make.catalog_medication(active_ingredient="Amlodipin besilat")
    without = make.catalog_medication(active_ingredient=None)
    a = _add(client, auth, patient, scheduled_body(with_text))
    b = _add(client, auth, patient, scheduled_body(without))
    assert a["medication"]["active_ingredient"] == "Amlodipin besilat"
    assert "active_ingredient" in b["medication"] and b["medication"]["active_ingredient"] is None

    items = {m["id"]: m for m in client.get("/medications", headers=auth(patient)).json()["items"]}
    assert items[a["id"]]["medication"]["active_ingredient"] == "Amlodipin besilat"
    assert items[b["id"]]["medication"]["active_ingredient"] is None
    single = client.get(f"/medications/{a['id']}", headers=auth(patient)).json()
    assert single["medication"]["active_ingredient"] == "Amlodipin besilat"
