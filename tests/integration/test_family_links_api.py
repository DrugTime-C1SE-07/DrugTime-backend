"""Test tích hợp HTTP API cho quản lý yêu cầu liên kết gia đình và consent (task 3.16).

Bao phủ các kịch bản I1, I2, I3, I4, I5, I6, I8 theo AC1–5, AC8–10, AC12–16, AC18.
Chạy trên PostgreSQL thật với api_role và auth token thật.
"""

from uuid import UUID

from sqlalchemy import text


def _create_pending_link(db, patient_id: UUID, family_id: UUID) -> int:
    return db.execute(
        text(
            "INSERT INTO caregiver_links "
            "(patient_user_id, family_user_id, status, sharing_enabled) "
            "VALUES (:p, :f, 'pending', false) RETURNING id"
        ),
        {"p": patient_id, "f": family_id},
    ).scalar_one()


# ==============================================================================
# I1: Pending grants no access (AC1)
# ==============================================================================


def test_pending_grants_no_access__AC1(client, db, make, auth):
    """AC1: Pending link có sharing_enabled=False, không có bằng chứng consent;

    family truy cập dữ liệu y tế bị 403 và có denied log.
    """
    patient = make.user(consents=("health_data", "family_sharing"))
    family = make.user()
    link_id = _create_pending_link(db, patient, family)

    med_id = make.catalog_medication()
    rx_id = db.execute(
        text(
            "INSERT INTO prescriptions (user_id, entry_source) "
            "VALUES (:u, 'mac_dinh') RETURNING id"
        ),
        {"u": patient},
    ).scalar_one()
    user_med_id = db.execute(
        text(
            "INSERT INTO user_medications (user_id, prescription_id, medication_id, "
            "entry_method, confirmation_status, quantity_per_dose, dosing_mode, doses_per_day) "
            "VALUES (:u, :rx, :m, 'thu_cong', 'da_xac_nhan', 1, 'khi_can', 1) RETURNING id"
        ),
        {"u": patient, "rx": rx_id, "m": med_id},
    ).scalar_one()

    # Xác nhận link trạng thái pending
    row = db.execute(
        text("SELECT status, sharing_enabled FROM caregiver_links WHERE id = :id"),
        {"id": link_id},
    ).one()
    assert row.status == "pending" and row.sharing_enabled is False

    # Chưa có bằng chứng consent confirmation
    confirmations = make.consent_confirmations(link_id)
    assert len(confirmations) == 0

    # Family gọi API y tế của patient -> 403 và có denied log
    r = client.get(f"/medications/{user_med_id}", headers=auth(family))
    assert r.status_code == 403
    logs = make.access_logs(patient)
    assert any(log["actor_user_id"] == family and log["result"] == "denied" for log in logs)


# ==============================================================================
# I2: List pending family links (AC12, AC13)
# ==============================================================================


def test_list_own_pending_minimal_order_without_consents__AC12_AC13(client, db, make, auth):
    """AC12, AC13: GET /family/links?status=pending

    - Chỉ trả về pending của caller.
    - Sắp xếp requested_at DESC, id DESC.
    - Metadata tối thiểu, tên có thể null, không email/sđt/mã liên kết.
    - Hoạt động kể cả khi patient chưa có consent y tế.
    - Ghi audit event allowed.
    """
    patient1 = make.user(consents=())  # Không có consent y tế nào
    patient2 = make.user(consents=())
    family1 = make.user()
    family2 = make.user()
    family3 = make.user()

    # Đặt tên cho family1, để trống tên cho family2
    db.execute(
        text("UPDATE users SET full_name = 'Nguyễn Văn An' WHERE id = :id"), {"id": family1}
    )
    db.execute(text("UPDATE users SET full_name = '   ' WHERE id = :id"), {"id": family2})

    # patient1: 2 pending links
    l1 = _create_pending_link(db, patient1, family1)
    l2 = _create_pending_link(db, patient1, family2)

    # patient1: 1 active link (không được xuất hiện trong pending)
    make.link(patient1, family3, status="active")

    # patient2: 1 pending link (không được xuất hiện trong danh sách của patient1)
    _create_pending_link(db, patient2, family1)

    r = client.get("/family/links?status=pending", headers=auth(patient1))
    assert r.status_code == 200
    data = r.json()
    assert "items" in data
    items = data["items"]
    assert len(items) == 2

    # Kiểm tra thứ tự và cấu trúc
    assert [item["link_id"] for item in items] == [l2, l1]

    # Kiểm tra các field cho phép
    item1 = next(it for it in items if it["link_id"] == l1)
    assert item1["family_user_id"] == str(family1)
    assert item1["family_full_name"] == "Nguyễn Văn An"
    assert item1["status"] == "pending"
    assert "requested_at" in item1
    assert "email" not in item1 and "phone" not in item1 and "link_code" not in item1

    # family2 tên trắng -> family_full_name là None
    item2 = next(it for it in items if it["link_id"] == l2)
    assert item2["family_full_name"] is None

    # Audit event được ghi
    audits = make.family_audit_events(patient_id=patient1, actor_id=patient1)
    assert any(a["operation"] == "list_pending" and a["result"] == "allowed" for a in audits)


def test_list_pending_empty_returns_200_items_empty__AC13(client, make, auth):
    """AC13: Patient không có pending -> trả 200 items: []."""
    patient = make.user(consents=())
    r = client.get("/family/links?status=pending", headers=auth(patient))
    assert r.status_code == 200
    assert r.json() == {"items": []}


# ==============================================================================
# I3: Approve confirmation matrix and consent requirements (AC2–4, AC10, AC16)
# ==============================================================================


def test_approve_success_persists_evidence_and_activates_link__AC2(client, db, make, auth):
    """AC2: Patient có family_sharing, approve pending hợp lệ:

    - Link active, sharing_enabled=False.
    - Lưu bằng chứng trong family_link_consent_confirmations.
    - Ghi audit event approve allowed.
    """
    patient = make.user(consents=("family_sharing",))
    family = make.user()
    link_id = _create_pending_link(db, patient, family)

    body = {
        "family_user_id": str(family),
        "consent_confirmed": True,
        "document_version": "2026-10-v1",
    }
    r = client.post(f"/family/links/{link_id}/approve", json=body, headers=auth(patient))
    assert r.status_code == 200
    res = r.json()
    assert res["link_id"] == link_id
    assert res["family_user_id"] == str(family)
    assert res["status"] == "active"
    assert res["sharing_enabled"] is False
    assert res["consent_confirmation"]["purpose"] == "family_sharing"
    assert res["consent_confirmation"]["document_version"] == "2026-10-v1"
    assert "confirmed_at" in res["consent_confirmation"]

    # Kiểm tra DB
    row = db.execute(
        text("SELECT status, sharing_enabled FROM caregiver_links WHERE id = :id"),
        {"id": link_id},
    ).one()
    assert row.status == "active" and row.sharing_enabled is False

    confirmations = make.consent_confirmations(link_id)
    assert len(confirmations) == 1
    assert confirmations[0]["patient_user_id"] == patient
    assert confirmations[0]["family_user_id"] == family
    assert confirmations[0]["purpose"] == "family_sharing"

    # Audit allowed
    audits = make.family_audit_events(patient_id=patient, actor_id=patient)
    assert any(
        a["operation"] == "approve" and a["result"] == "allowed" and a["link_id"] == link_id
        for a in audits
    )


def test_approve_denied_caller_matrix__AC4_AC10_AC16(client, db, make, auth, admin_auth):
    """AC4, AC10, AC16:

    - Chưa đăng nhập -> 401.
    - Family gọi duyệt thay -> 403.
    - Người lạ gọi duyệt thay -> 403.
    - Admin gọi duyệt thay -> 403.
    - Sai family_user_id trong body -> 403.
    Mọi trường hợp 403 ghi audit denied riêng, DB không đổi.
    """
    patient = make.user(consents=("family_sharing",))
    family = make.user()
    stranger = make.user()
    _, admin_header = admin_auth
    link_id = _create_pending_link(db, patient, family)

    body = {
        "family_user_id": str(family),
        "consent_confirmed": True,
        "document_version": "2026-10-v1",
    }

    # 401 khi không đăng nhập
    assert client.post(f"/family/links/{link_id}/approve", json=body).status_code == 401

    # 403 family duyệt thay
    r_fam = client.post(f"/family/links/{link_id}/approve", json=body, headers=auth(family))
    assert r_fam.status_code == 403 and r_fam.json()["detail"] == "khong_co_quyen"

    # 403 stranger duyệt thay
    r_str = client.post(f"/family/links/{link_id}/approve", json=body, headers=auth(stranger))
    assert r_str.status_code == 403 and r_str.json()["detail"] == "khong_co_quyen"

    # 403 admin duyệt thay
    r_adm = client.post(f"/family/links/{link_id}/approve", json=body, headers=admin_header)
    assert r_adm.status_code == 403 and r_adm.json()["detail"] == "khong_co_quyen"

    # 403 sai family_user_id trong body
    wrong_body = {
        "family_user_id": str(stranger),
        "consent_confirmed": True,
        "document_version": "2026-10-v1",
    }
    r_wrong = client.post(
        f"/family/links/{link_id}/approve", json=wrong_body, headers=auth(patient)
    )
    assert r_wrong.status_code == 403 and r_wrong.json()["detail"] == "khong_co_quyen"

    # DB không đổi
    row = db.execute(
        text("SELECT status FROM caregiver_links WHERE id = :id"), {"id": link_id}
    ).one()
    assert row.status == "pending"
    assert len(make.consent_confirmations(link_id)) == 0

    # Có denied audit logs
    audits = make.family_audit_events(patient_id=patient)
    denied_reasons = [a["reason"] for a in audits if a["result"] == "denied"]
    assert "khong_co_quyen" in denied_reasons


def test_approve_missing_or_revoked_patient_consent_403__AC3_AC10(client, db, make, auth):
    """AC3, AC10: Patient thiếu hoặc đã rút family_sharing -> 403 consent_revoked."""
    patient = make.user(consents=())  # Chưa có family_sharing
    family = make.user(consents=("family_sharing",))  # Family có nhưng không thay thế được
    link_id = _create_pending_link(db, patient, family)

    body = {
        "family_user_id": str(family),
        "consent_confirmed": True,
        "document_version": "2026-10-v1",
    }
    r = client.post(f"/family/links/{link_id}/approve", json=body, headers=auth(patient))
    assert r.status_code == 403
    assert r.json()["detail"] == "consent_revoked"

    # Rút consent sau khi đã cấp
    make.consent(patient, "family_sharing")
    make.revoke_consent(patient, "family_sharing")

    r2 = client.post(f"/family/links/{link_id}/approve", json=body, headers=auth(patient))
    assert r2.status_code == 403
    assert r2.json()["detail"] == "consent_revoked"


def test_approve_outdated_version_and_false_confirmation_422__AC3(client, db, make, auth):
    """AC3: document_version sai -> 422 consent_document_outdated;

    consent_confirmed=False -> 422 validation error.
    """
    patient = make.user(consents=("family_sharing",))
    family = make.user()
    link_id = _create_pending_link(db, patient, family)

    # Version sai
    r1 = client.post(
        f"/family/links/{link_id}/approve",
        json={
            "family_user_id": str(family),
            "consent_confirmed": True,
            "document_version": "wrong-version",
        },
        headers=auth(patient),
    )
    assert r1.status_code == 422
    assert r1.json()["detail"] == "consent_document_outdated"

    # confirmation=False
    r2 = client.post(
        f"/family/links/{link_id}/approve",
        json={
            "family_user_id": str(family),
            "consent_confirmed": False,
            "document_version": "2026-10-v1",
        },
        headers=auth(patient),
    )
    assert r2.status_code == 422


def test_approve_not_found_404(client, make, auth):
    """404 family_link_not_found khi link_id không tồn tại."""
    patient = make.user(consents=("family_sharing",))
    family = make.user()
    r = client.post(
        "/family/links/99999999/approve",
        json={
            "family_user_id": str(family),
            "consent_confirmed": True,
            "document_version": "2026-10-v1",
        },
        headers=auth(patient),
    )
    assert r.status_code == 404
    assert r.json()["detail"] == "family_link_not_found"


# ==============================================================================
# I4: Approve replay, version conflict, legacy conflict (AC5, AC8, AC9, AC11)
# ==============================================================================


def test_approve_replay_idempotent_with_same_evidence__AC5_AC9(client, db, make, auth):
    """AC5, AC9: Replay approve đúng cặp và đúng payload:

    - Trả về 200 với cùng evidence id và confirmed_at cũ.
    - Không chèn thêm record vào family_link_consent_confirmations.
    """
    patient = make.user(consents=("family_sharing",))
    family = make.user()
    link_id = _create_pending_link(db, patient, family)

    body = {
        "family_user_id": str(family),
        "consent_confirmed": True,
        "document_version": "2026-10-v1",
    }
    r1 = client.post(f"/family/links/{link_id}/approve", json=body, headers=auth(patient))
    assert r1.status_code == 200
    data1 = r1.json()

    # Replay lần 2
    r2 = client.post(f"/family/links/{link_id}/approve", json=body, headers=auth(patient))
    assert r2.status_code == 200
    data2 = r2.json()

    assert data1["consent_confirmation"]["id"] == data2["consent_confirmation"]["id"]
    assert (
        data1["consent_confirmation"]["confirmed_at"]
        == data2["consent_confirmation"]["confirmed_at"]
    )
    assert len(make.consent_confirmations(link_id)) == 1


def test_approve_replay_returns_current_sharing_enabled__AC9(client, db, make, auth):
    """AC9: Replay approve trả lại giá trị sharing_enabled hiện tại của link."""
    patient = make.user(consents=("family_sharing",))
    family = make.user()
    link_id = _create_pending_link(db, patient, family)

    body = {
        "family_user_id": str(family),
        "consent_confirmed": True,
        "document_version": "2026-10-v1",
    }
    client.post(f"/family/links/{link_id}/approve", json=body, headers=auth(patient))

    # Giả lập bật sharing_enabled = True (PB18)
    db.execute(
        text("UPDATE caregiver_links SET sharing_enabled = true WHERE id = :id"), {"id": link_id}
    )

    r_replay = client.post(f"/family/links/{link_id}/approve", json=body, headers=auth(patient))
    assert r_replay.status_code == 200
    assert r_replay.json()["sharing_enabled"] is True


def test_approve_replay_different_version_conflict_409__AC9(client, db, make, auth):
    """AC9: Replay trên link active với version khác trả 409 conflict."""
    patient = make.user(consents=("family_sharing",))
    family = make.user()
    link_id = _create_pending_link(db, patient, family)

    client.post(
        f"/family/links/{link_id}/approve",
        json={
            "family_user_id": str(family),
            "consent_confirmed": True,
            "document_version": "2026-10-v1",
        },
        headers=auth(patient),
    )

    r_conflict = client.post(
        f"/family/links/{link_id}/approve",
        json={
            "family_user_id": str(family),
            "consent_confirmed": True,
            "document_version": "2026-11-v2",
        },
        headers=auth(patient),
    )
    assert r_conflict.status_code == 409
    assert r_conflict.json()["detail"] == "link_approval_conflict"


def test_approve_legacy_active_missing_evidence_conflict_409__AC11(client, make, auth):
    """AC11: Link active legacy thiếu evidence trả 409."""
    patient = make.user(consents=("family_sharing",))
    family = make.user()
    link_id = make.link(patient, family, status="active", legacy=True)

    r = client.post(
        f"/family/links/{link_id}/approve",
        json={
            "family_user_id": str(family),
            "consent_confirmed": True,
            "document_version": "2026-10-v1",
        },
        headers=auth(patient),
    )
    assert r.status_code == 409
    assert r.json()["detail"] == "consent_confirmation_missing"


def test_approve_rejected_or_revoked_conflict_409__AC8(client, make, auth):
    """AC8: Link rejected hoặc revoked -> approve trả 409 invalid_link_transition."""
    patient = make.user(consents=("family_sharing",))
    family = make.user()
    l_rej = make.link(patient, family, status="rejected", legacy=True)

    family2 = make.user()
    l_rev = make.link(patient, family2, status="revoked", legacy=True)

    body = {
        "family_user_id": str(family),
        "consent_confirmed": True,
        "document_version": "2026-10-v1",
    }
    r_rej = client.post(f"/family/links/{l_rej}/approve", json=body, headers=auth(patient))
    assert r_rej.status_code == 409
    assert r_rej.json()["detail"] == "invalid_link_transition"

    body["family_user_id"] = str(family2)
    r_rev = client.post(f"/family/links/{l_rev}/approve", json=body, headers=auth(patient))
    assert r_rev.status_code == 409
    assert r_rev.json()["detail"] == "invalid_link_transition"


# ==============================================================================
# I5: Reject without consent and replay (AC14, AC15)
# ==============================================================================


def test_reject_without_consent_and_replay_idempotent__AC14_AC15(client, db, make, auth):
    """AC14, AC15:

    - Patient reject pending: không cần consent y tế, chuyển rejected, lưu rejected_at.
    - Không tạo bằng chứng consent.
    - Replay reject: trả 200 giữ nguyên rejected_at cũ.
    """
    patient = make.user(consents=())  # Không có consent
    family = make.user()
    link_id = _create_pending_link(db, patient, family)

    # Reject lần 1
    r1 = client.post(f"/family/links/{link_id}/reject", headers=auth(patient))
    assert r1.status_code == 200
    data1 = r1.json()
    assert data1["link_id"] == link_id
    assert data1["family_user_id"] == str(family)
    assert data1["status"] == "rejected"
    assert "rejected_at" in data1

    # DB kiểm tra
    row = db.execute(
        text("SELECT status, rejected_at FROM caregiver_links WHERE id = :id"), {"id": link_id}
    ).one()
    assert row.status == "rejected" and row.rejected_at is not None

    # Không có evidence được sinh ra
    assert len(make.consent_confirmations(link_id)) == 0

    # Replay reject lần 2
    r2 = client.post(f"/family/links/{link_id}/reject", headers=auth(patient))
    assert r2.status_code == 200
    data2 = r2.json()
    assert data1["rejected_at"] == data2["rejected_at"]

    # Audit được ghi nhận cho cả hai lần
    audits = make.family_audit_events(patient_id=patient, actor_id=patient)
    reject_audits = [
        a for a in audits if a["operation"] == "reject" and a["result"] == "allowed"
    ]
    assert len(reject_audits) == 2


def test_reject_active_or_revoked_conflict_409__AC15(client, make, auth):
    """AC15: Link active hoặc revoked -> reject trả 409 invalid_link_transition."""
    patient = make.user(consents=("family_sharing",))
    family = make.user()
    l_act = make.link(patient, family, status="active")

    family2 = make.user()
    l_rev = make.link(patient, family2, status="revoked", legacy=True)

    r_act = client.post(f"/family/links/{l_act}/reject", headers=auth(patient))
    assert r_act.status_code == 409
    assert r_act.json()["detail"] == "invalid_link_transition"

    r_rev = client.post(f"/family/links/{l_rev}/reject", headers=auth(patient))
    assert r_rev.status_code == 409
    assert r_rev.json()["detail"] == "invalid_link_transition"


# ==============================================================================
# I6: Strict HTTP inputs and forbidden cases (AC4, AC10, AC12, AC16)
# ==============================================================================


def test_strict_http_inputs_and_forbidden_cases__AC12_AC16(client, db, make, auth, admin_auth):
    """AC12, AC16:

    - GET từ chối query lạ, status!=pending, body.
    - Approve/reject từ chối query, body thừa, reject có body.
    - Admin bị chặn GET trước lookup (ghi denied audit không link/patient).
    - Admin bị chặn reject.
    """
    patient = make.user(consents=("family_sharing",))
    family = make.user()
    link_id = _create_pending_link(db, patient, family)
    admin_id, admin_header = admin_auth

    # GET thiếu query status
    assert client.get("/family/links", headers=auth(patient)).status_code == 422
    # GET status sai
    assert client.get("/family/links?status=active", headers=auth(patient)).status_code == 422
    # GET có patient_id
    assert (
        client.get(
            f"/family/links?status=pending&patient_id={patient}", headers=auth(patient)
        ).status_code
        == 422
    )

    # Approve có query param
    assert (
        client.post(
            f"/family/links/{link_id}/approve?extra=1",
            json={
                "family_user_id": str(family),
                "consent_confirmed": True,
                "document_version": "2026-10-v1",
            },
            headers=auth(patient),
        ).status_code
        == 422
    )

    # Approve có body extra field
    assert (
        client.post(
            f"/family/links/{link_id}/approve",
            json={
                "family_user_id": str(family),
                "consent_confirmed": True,
                "document_version": "2026-10-v1",
                "hacker_field": "injected",
            },
            headers=auth(patient),
        ).status_code
        == 422
    )

    # Reject có body
    assert (
        client.post(
            f"/family/links/{link_id}/reject", json={"reason": "bye"}, headers=auth(patient)
        ).status_code
        == 422
    )

    # Reject có query param
    assert (
        client.post(f"/family/links/{link_id}/reject?reason=bye", headers=auth(patient)).status_code
        == 422
    )

    # Admin gọi GET -> 403 trước khi lookup, audit denied
    r_adm_get = client.get("/family/links?status=pending", headers=admin_header)
    assert r_adm_get.status_code == 403 and r_adm_get.json()["detail"] == "khong_co_quyen"

    admin_audits = make.family_audit_events(actor_id=admin_id)
    assert any(
        a["operation"] == "list_pending"
        and a["result"] == "denied"
        and a["patient_user_id"] is None
        and a["link_id"] is None
        for a in admin_audits
    )

    # Admin gọi reject -> 403
    r_adm_rej = client.post(f"/family/links/{link_id}/reject", headers=admin_header)
    assert r_adm_rej.status_code == 403 and r_adm_rej.json()["detail"] == "khong_co_quyen"


# ==============================================================================
# I8: Storage and audit commit failures fail-closed (AC4, AC5, AC18)
# ==============================================================================


def test_storage_commit_failure_returns_503_and_rolls_back__AC18(
    client, db, make, auth, monkeypatch
):
    """AC18: Khi commit thất bại, trả 503 service_unavailable và rollback hoàn toàn,

    không để lại link active dở dang hoặc bằng chứng orphan.
    """
    patient = make.user(consents=("family_sharing",))
    family = make.user()
    link_id = _create_pending_link(db, patient, family)

    from contextlib import contextmanager

    from sqlalchemy.exc import OperationalError

    from drugtime.shared.db import unit_of_work

    @contextmanager
    def failing_unit_of_work():
        with unit_of_work() as uow:
            yield uow
            raise OperationalError("database connection lost during commit", {}, None)

    monkeypatch.setattr(
        "drugtime.modules.family.adapters.inbound.http.unit_of_work",
        failing_unit_of_work,
    )

    body = {
        "family_user_id": str(family),
        "consent_confirmed": True,
        "document_version": "2026-10-v1",
    }
    r = client.post(f"/family/links/{link_id}/approve", json=body, headers=auth(patient))
    assert r.status_code == 503
    assert r.json()["detail"] == "service_unavailable"

    # Kiểm tra DB trạng thái sau rollback: link vẫn pending, không có evidence
    row = db.execute(
        text("SELECT status FROM caregiver_links WHERE id = :id"), {"id": link_id}
    ).one()
    assert row.status == "pending"
    assert len(make.consent_confirmations(link_id)) == 0


def test_denied_audit_persists_even_when_use_case_fails__AC18(client, db, make, auth):
    """AC18: Audit denied được ghi ở transaction riêng biệt (fail-closed),

    vẫn tồn tại sau khi request bị từ chối 403.
    """
    patient = make.user(consents=())  # Thiếu consent -> 403
    family = make.user()
    link_id = _create_pending_link(db, patient, family)

    body = {
        "family_user_id": str(family),
        "consent_confirmed": True,
        "document_version": "2026-10-v1",
    }
    r = client.post(f"/family/links/{link_id}/approve", json=body, headers=auth(patient))
    assert r.status_code == 403

    audits = make.family_audit_events(patient_id=patient)
    assert any(
        a["operation"] == "approve"
        and a["result"] == "denied"
        and a["reason"] == "consent_revoked"
        for a in audits
    )


def test_denied_audit_writer_failure_fails_closed__AC18(db, make, auth, monkeypatch):
    """Không ghi được denied audit thì request không được trả thành công."""
    from fastapi.testclient import TestClient

    from drugtime.main import create_app
    from drugtime.modules.family.adapters.outbound.sql_link_audit import SqlLinkAudit

    patient = make.user(consents=("family_sharing",))
    other = make.user()
    family = make.user()
    link_id = _create_pending_link(db, patient, family)

    def broken(*_args, **_kwargs):
        raise RuntimeError("family_link_audit_events unavailable")

    monkeypatch.setattr(SqlLinkAudit, "denied", broken)
    response = TestClient(create_app(), raise_server_exceptions=False).post(
        f"/family/links/{link_id}/reject", headers=auth(other)
    )

    assert response.status_code >= 500
    assert db.execute(
        text("SELECT status FROM caregiver_links WHERE id = :id"), {"id": link_id}
    ).scalar_one() == "pending"
    assert not make.family_audit_events(patient_id=patient)


# ==============================================================================
# adhoc-20261020-family-link-approval: reject chỉ dành cho đúng patient (AC5)
# ==============================================================================


def test_reject_denied_caller_matrix__AC5(client, make, auth, admin_auth):
    """Người thân của link, người lạ và admin từ chối thay → 403, link vẫn pending, mỗi lượt
    đúng một audit denied với actor là người gọi; patient từ chối được (cặp allowed)."""
    patient = make.user(consents=("family_sharing",))
    family, stranger = make.user(), make.user()
    admin_id, admin_header = admin_auth
    link_id = make.pending_link(patient, family)

    assert client.post(f"/family/links/{link_id}/reject").status_code == 401
    for actor, headers in (
        (family, auth(family)),
        (stranger, auth(stranger)),
        (admin_id, admin_header),
    ):
        r = client.post(f"/family/links/{link_id}/reject", headers=headers)
        assert r.status_code == 403 and r.json() == {"detail": "khong_co_quyen"}
        denied = make.family_audit_events(actor_id=actor)
        assert [(a["operation"], a["result"], a["reason"]) for a in denied] == [
            ("reject", "denied", "khong_co_quyen")
        ]
        # Admin bị chặn trước khi tra cứu link nên không ghi patient/link.
        expected_scope = (None, None) if actor == admin_id else (patient, link_id)
        assert (denied[0]["patient_user_id"], denied[0]["link_id"]) == expected_scope
        assert make.link_row(link_id)["status"] == "pending"

    r = client.post(f"/family/links/{link_id}/reject", headers=auth(patient))
    assert r.status_code == 200 and r.json()["status"] == "rejected"
    assert make.link_row(link_id)["status"] == "rejected"
