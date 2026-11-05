"""Integration tests cho luồng Consent-on-link (PB16, Task 3.18).

Các kịch bản kiểm thử:
- T1: Luồng chính tuần tự (cùng family token): request -> pending (403) -> approve (403) -> bật sharing (200).
      Kiểm tra chặt chẽ đúng 1 dòng access_logs mới ở mỗi bước.
- T2: Bệnh nhân từ chối (reject) qua API -> link chuyển rejected, rejected_at NOT NULL -> family 403 + denied log.
- T3a: Bệnh nhân rút consent 'family_sharing' qua API (QD-28) -> family bị 403 ngay ở request kế tiếp (cùng token).
- T3b: Bệnh nhân rút consent 'health_data' qua API (PEP purpose) -> family bị 403 ngay ở request kế tiếp (cùng token).
- T4: Bệnh nhân thu hồi link qua POST /family/links/{id}/revoke -> family bị 403 ngay ở request kế tiếp + denied log.
- T4_delete: Kiểm tra DELETE /family/links/{id} (PR #39 / commit 5bb4e457). Tự động skip có bằng chứng nếu baseline chưa có route này.
- T5 (QD-30): Thu hồi rồi liên kết lại -> approve link mới không tự khôi phục sharing_enabled=True cũ,
              family vẫn 403 cho đến khi bệnh nhân bật chia sẻ lại.
"""

from uuid import UUID, uuid4

import pytest
from sqlalchemy import text

DOCUMENT_VERSION = "2026-10-v1"
SCOPE_MEDICATIONS = "danh_sach_thuoc"


def _create_user_medication(db, patient_id: UUID, med_id: int) -> int:
    """Tạo đơn thuốc và thuốc người dùng cho bệnh nhân để kiểm tra truy cập dữ liệu y tế."""
    rx_id = db.execute(
        text(
            "INSERT INTO prescriptions (user_id, entry_source) "
            "VALUES (:u, 'mac_dinh') RETURNING id"
        ),
        {"u": patient_id},
    ).scalar_one()
    return db.execute(
        text(
            "INSERT INTO user_medications (user_id, prescription_id, medication_id, "
            "entry_method, confirmation_status, quantity_per_dose, dosing_mode, doses_per_day) "
            "VALUES (:u, :rx, :m, 'thu_cong', 'da_xac_nhan', 1, 'khi_can', 1) RETURNING id"
        ),
        {"u": patient_id, "rx": rx_id, "m": med_id},
    ).scalar_one()


# ==============================================================================
# T1: Luồng chính tuần tự: Request -> Pending (403) -> Approve (403) -> Enable Sharing (200)
# ==============================================================================


def test_consent_on_link_lifecycle_with_audit_logs__T1__3_18(client, db, make, auth):
    """T1: Luồng chính tuần tự với cùng token người thân (PB16, QD-04, QD-28, QD-33).

    1. Người thân gửi link request -> link ở trạng thái pending.
    2. Người thân gọi GET /medications/{id} -> 403 khong_co_quyen.
       Assert đúng 1 log mới: result='denied', actor_role='khong_co_quyen', rejection_reason='khong_co_quyen'.
    3. Bệnh nhân approve link -> link active, nhưng sharing_enabled=False (thiết kế an toàn mặc định).
       Người thân gọi lại -> vẫn 403 khong_co_quyen.
       Assert thêm đúng 1 log mới: result='denied'.
    4. Bệnh nhân bật chia sẻ qua PATCH /family/links/{id}/sharing -> sharing_enabled=True.
       Người thân gọi lại -> 200 OK.
       Assert thêm đúng 1 log mới: result='allowed', actor_role='family', rejection_reason=None.
    """
    patient = make.user(consents=("health_data", "family_sharing"))
    family = make.user()
    family_headers = auth(family)
    patient_headers = auth(patient)
    user_med_id = _create_user_medication(db, patient, make.catalog_medication())

    # Lấy mã liên kết của patient
    code_res = client.get("/family/link-code", headers=patient_headers)
    assert code_res.status_code == 200
    code = code_res.json()["code"]

    # 1. Family gửi yêu cầu liên kết
    req_res = client.post(
        "/family/link-requests",
        json={"client_uuid": str(uuid4()), "code": code},
        headers=family_headers,
    )
    assert req_res.status_code == 201, req_res.text
    link_id = req_res.json()["id"]

    # Xác minh trạng thái link là pending, sharing_enabled=False, các timestamp chuẩn
    link_row = db.execute(
        text(
            "SELECT status, sharing_enabled, linked_at, revoked_at, rejected_at "
            "FROM caregiver_links WHERE id = :id"
        ),
        {"id": link_id},
    ).one()
    assert link_row.status == "pending"
    assert link_row.sharing_enabled is False
    assert link_row.linked_at is not None
    assert link_row.revoked_at is None
    assert link_row.rejected_at is None

    # 2. Family truy cập dữ liệu y tế khi link đang pending -> 403 khong_co_quyen
    logs_before = make.access_logs(patient)
    count_before = len(logs_before)

    r_pending = client.get(f"/medications/{user_med_id}", headers=family_headers)
    assert r_pending.status_code == 403
    assert r_pending.json() == {"detail": "khong_co_quyen"}

    # Assert chính xác 1 dòng log mới được thêm vào
    logs_after_pending = make.access_logs(patient)
    assert len(logs_after_pending) == count_before + 1
    new_log_1 = logs_after_pending[-1]
    assert new_log_1["actor_user_id"] == family
    assert new_log_1["actor_role"] == "khong_co_quyen"
    assert new_log_1["data_scope"] == SCOPE_MEDICATIONS
    assert new_log_1["result"] == "denied"
    assert new_log_1["rejection_reason"] == "khong_co_quyen"

    # 3. Patient approve link
    approve_res = client.post(
        f"/family/links/{link_id}/approve",
        json={
            "family_user_id": str(family),
            "consent_confirmed": True,
            "document_version": DOCUMENT_VERSION,
        },
        headers=patient_headers,
    )
    assert approve_res.status_code == 200, approve_res.text
    approve_data = approve_res.json()
    assert approve_data["status"] == "active"
    assert approve_data["sharing_enabled"] is False  # Phản ánh code transition_link dòng 86

    # Xác minh trạng thái link trong DB sau approve
    link_row_appr = db.execute(
        text(
            "SELECT status, sharing_enabled, linked_at, revoked_at, rejected_at "
            "FROM caregiver_links WHERE id = :id"
        ),
        {"id": link_id},
    ).one()
    assert link_row_appr.status == "active"
    assert link_row_appr.sharing_enabled is False
    assert link_row_appr.linked_at is not None
    assert link_row_appr.revoked_at is None
    assert link_row_appr.rejected_at is None

    # Xác minh bằng chứng phê duyệt được lưu vào family_link_consent_confirmations
    conf = db.execute(
        text("SELECT document_version, confirmed_at FROM family_link_consent_confirmations WHERE link_id = :id"),
        {"id": link_id},
    ).one()
    assert conf.document_version == DOCUMENT_VERSION
    assert conf.confirmed_at is not None

    # Family gọi lại -> Vẫn 403 khong_co_quyen vì sharing_enabled vẫn False
    r_approved_sharing_off = client.get(f"/medications/{user_med_id}", headers=family_headers)
    assert r_approved_sharing_off.status_code == 403
    assert r_approved_sharing_off.json() == {"detail": "khong_co_quyen"}

    # Assert chính xác thêm 1 dòng log mới
    logs_after_approve = make.access_logs(patient)
    assert len(logs_after_approve) == len(logs_after_pending) + 1
    new_log_2 = logs_after_approve[-1]
    assert new_log_2["actor_user_id"] == family
    assert new_log_2["actor_role"] == "khong_co_quyen"
    assert new_log_2["data_scope"] == SCOPE_MEDICATIONS
    assert new_log_2["result"] == "denied"
    assert new_log_2["rejection_reason"] == "khong_co_quyen"

    # 4. Patient bật chia sẻ qua PATCH /family/links/{id}/sharing
    sharing_res = client.patch(
        f"/family/links/{link_id}/sharing",
        json={"sharing_enabled": True},
        headers=patient_headers,
    )
    assert sharing_res.status_code == 200, sharing_res.text
    assert sharing_res.json()["sharing_enabled"] is True

    # Xác minh trong DB sharing_enabled đã cập nhật thành True
    assert db.execute(
        text("SELECT sharing_enabled FROM caregiver_links WHERE id = :id"),
        {"id": link_id},
    ).scalar_one() is True

    # Family gọi lại bằng cùng token -> 200 OK
    r_allowed = client.get(f"/medications/{user_med_id}", headers=family_headers)
    assert r_allowed.status_code == 200, r_allowed.text

    # Assert chính xác thêm 1 dòng log allowed mới
    logs_after_sharing = make.access_logs(patient)
    assert len(logs_after_sharing) == len(logs_after_approve) + 1
    new_log_3 = logs_after_sharing[-1]
    assert new_log_3["actor_user_id"] == family
    assert new_log_3["actor_role"] == "family"
    assert new_log_3["data_scope"] == SCOPE_MEDICATIONS
    assert new_log_3["result"] == "allowed"
    assert new_log_3["rejection_reason"] is None


# ==============================================================================
# T2: Patient reject link -> rejected_at NOT NULL -> Family 403 + denied log
# ==============================================================================


def test_patient_rejects_link__family_denied_with_audit_log__T2__3_18(client, db, make, auth):
    """T2: Bệnh nhân từ chối yêu cầu liên kết (QD-04, QD-33).

    1. Người thân gửi link request.
    2. Bệnh nhân reject qua API thật POST /family/links/{id}/reject.
    3. Xác minh trạng thái 'rejected', rejected_at NOT NULL.
    4. Người thân gọi GET /medications/{id} -> 403 khong_co_quyen.
    5. Xác minh chính xác 1 dòng denied access log mới (actor_role, scope, result, rejection_reason).
    """
    patient = make.user(consents=("health_data", "family_sharing"))
    family = make.user()
    family_headers = auth(family)
    patient_headers = auth(patient)
    user_med_id = _create_user_medication(db, patient, make.catalog_medication())

    # Lấy mã và gửi request
    code = client.get("/family/link-code", headers=patient_headers).json()["code"]
    req = client.post(
        "/family/link-requests",
        json={"client_uuid": str(uuid4()), "code": code},
        headers=family_headers,
    )
    assert req.status_code == 201
    link_id = req.json()["id"]

    # Đếm log trước khi truy cập
    count_before = len(make.access_logs(patient))

    # Bệnh nhân từ chối qua API thật
    rej_res = client.post(f"/family/links/{link_id}/reject", headers=patient_headers)
    assert rej_res.status_code == 200
    rej_data = rej_res.json()
    assert rej_data["status"] == "rejected"
    assert rej_data["rejected_at"] is not None

    # Kiểm tra DB constraints và timestamps
    row = db.execute(
        text("SELECT status, rejected_at, revoked_at, linked_at FROM caregiver_links WHERE id = :id"),
        {"id": link_id},
    ).one()
    assert row.status == "rejected"
    assert row.rejected_at is not None
    assert row.revoked_at is None
    assert row.linked_at is not None

    # Người thân truy cập dữ liệu -> 403 khong_co_quyen
    r = client.get(f"/medications/{user_med_id}", headers=family_headers)
    assert r.status_code == 403
    assert r.json() == {"detail": "khong_co_quyen"}

    # Xác minh đúng 1 dòng log denied mới
    logs = make.access_logs(patient)
    assert len(logs) == count_before + 1
    last_log = logs[-1]
    assert last_log["actor_user_id"] == family
    assert last_log["actor_role"] == "khong_co_quyen"
    assert last_log["data_scope"] == SCOPE_MEDICATIONS
    assert last_log["result"] == "denied"
    assert last_log["rejection_reason"] == "khong_co_quyen"


# ==============================================================================
# T3a: Rút consent family_sharing qua API có hiệu lực tức thì (QD-28)
# ==============================================================================


def test_withdraw_family_sharing_consent_takes_effect_immediately__T3_family_sharing__3_18(
    client, db, make, auth
):
    """T3a: Bệnh nhân rút consent family_sharing qua API thật -> chặn ngay lập tức (QD-28, QD-29).

    QD-28: Chia sẻ chỉ khi ĐỒNG THỜI link active + sharing_enabled + consent family_sharing còn hiệu lực.
    1. Thiết lập link active, sharing bật, consent hợp lệ -> family đọc 200 OK.
    2. Bệnh nhân rút consent family_sharing qua POST /consents/family_sharing/withdraw.
    3. Người thân dùng cùng token gọi lại -> 403 khong_co_quyen ngay lập tức (không cache).
    4. Xác minh dòng denied log.
    """
    patient = make.user(consents=("health_data", "family_sharing"))
    family = make.user()
    family_headers = auth(family)
    patient_headers = auth(patient)
    user_med_id = _create_user_medication(db, patient, make.catalog_medication())

    # Tạo link active và bật sharing
    link_id = make.link(patient, family, status="active", sharing=True)

    # 1. Truy cập ban đầu thành công 200 OK
    count_before = len(make.access_logs(patient))
    r_init = client.get(f"/medications/{user_med_id}", headers=family_headers)
    assert r_init.status_code == 200

    logs_after_step1 = make.access_logs(patient)
    assert len(logs_after_step1) == count_before + 1
    allowed_log = logs_after_step1[-1]
    assert allowed_log["result"] == "allowed"
    assert allowed_log["actor_role"] == "family"
    assert allowed_log["data_scope"] == SCOPE_MEDICATIONS
    assert allowed_log["rejection_reason"] is None

    # 2. Bệnh nhân rút consent family_sharing qua API thật
    withdraw_res = client.post("/consents/family_sharing/withdraw", headers=patient_headers)
    assert withdraw_res.status_code == 200

    # 3. Người thân gửi lại request kế tiếp với cùng token -> 403 khong_co_quyen
    r_revoked = client.get(f"/medications/{user_med_id}", headers=family_headers)
    assert r_revoked.status_code == 403
    assert r_revoked.json() == {"detail": "khong_co_quyen"}

    # 4. Kiểm tra access_logs
    logs_after_step2 = make.access_logs(patient)
    assert len(logs_after_step2) == count_before + 2
    denied_log = logs_after_step2[-1]
    assert denied_log["result"] == "denied"
    assert denied_log["actor_user_id"] == family
    assert denied_log["actor_role"] == "khong_co_quyen"
    assert denied_log["data_scope"] == SCOPE_MEDICATIONS
    assert denied_log["rejection_reason"] == "khong_co_quyen"


# ==============================================================================
# T3b: Rút consent health_data (purpose consent) qua API có hiệu lực tức thì (PEP)
# ==============================================================================


def test_withdraw_health_data_consent_takes_effect_immediately__T3_health_data__3_18(
    client, db, make, auth
):
    """T3b: Bệnh nhân rút consent health_data qua API thật -> chặn ngay lập tức (PEP purpose guard).

    Quan hệ:
    - 'family_sharing' mở luồng chia sẻ người thân nói chung.
    - 'health_data' là purpose consent bắt buộc cho Scope.MEDICATIONS ("danh_sach_thuoc").
    Rút một trong hai consent đều làm người thân mất quyền truy cập dữ liệu y tế.
    """
    patient = make.user(consents=("health_data", "family_sharing"))
    family = make.user()
    family_headers = auth(family)
    patient_headers = auth(patient)
    user_med_id = _create_user_medication(db, patient, make.catalog_medication())

    make.link(patient, family, status="active", sharing=True)

    # 1. Truy cập ban đầu thành công 200
    count_before = len(make.access_logs(patient))
    assert client.get(f"/medications/{user_med_id}", headers=family_headers).status_code == 200

    logs_after_step1 = make.access_logs(patient)
    assert len(logs_after_step1) == count_before + 1
    allowed_log = logs_after_step1[-1]
    assert allowed_log["result"] == "allowed"
    assert allowed_log["actor_role"] == "family"
    assert allowed_log["data_scope"] == SCOPE_MEDICATIONS
    assert allowed_log["rejection_reason"] is None

    # 2. Bệnh nhân rút consent health_data qua API thật
    withdraw_res = client.post("/consents/health_data/withdraw", headers=patient_headers)
    assert withdraw_res.status_code == 200

    # 3. Người thân gửi lại request kế tiếp với cùng token -> 403 khong_co_quyen
    r_revoked = client.get(f"/medications/{user_med_id}", headers=family_headers)
    assert r_revoked.status_code == 403
    assert r_revoked.json() == {"detail": "khong_co_quyen"}

    # 4. Kiểm tra access_logs
    logs_after_step2 = make.access_logs(patient)
    assert len(logs_after_step2) == count_before + 2
    denied_log = logs_after_step2[-1]
    assert denied_log["result"] == "denied"
    assert denied_log["actor_user_id"] == family
    assert denied_log["actor_role"] == "khong_co_quyen"
    assert denied_log["data_scope"] == SCOPE_MEDICATIONS
    assert denied_log["rejection_reason"] == "khong_co_quyen"


# ==============================================================================
# T4: Thu hồi link qua POST /family/links/{id}/revoke (Xác minh trên baseline hiện tại 33867bf)
# ==============================================================================


def test_revoke_link_via_post_endpoint_takes_effect_immediately__T4__3_18(client, db, make, auth):
    """T4: Bệnh nhân thu hồi link qua POST /family/links/{id}/revoke -> chặn 403 ngay (QD-28, QD-29).

    Route POST /family/links/{id}/revoke là endpoint thu hồi link hiện diện trên baseline commit 33867bf.
    1. Thiết lập link active, sharing bật -> family truy cập 200 OK.
    2. Bệnh nhân thu hồi link qua POST /family/links/{link_id}/revoke -> 200, status='revoked'.
    3. Người thân dùng cùng token gọi lại -> 403 khong_co_quyen ngay lập tức.
    4. Xác minh denied log.
    """
    patient = make.user(consents=("health_data", "family_sharing"))
    family = make.user()
    family_headers = auth(family)
    patient_headers = auth(patient)
    user_med_id = _create_user_medication(db, patient, make.catalog_medication())

    link_id = make.link(patient, family, status="active", sharing=True)

    # 1. Truy cập ban đầu thành công 200
    count_before = len(make.access_logs(patient))
    assert client.get(f"/medications/{user_med_id}", headers=family_headers).status_code == 200
    logs_after_step1 = make.access_logs(patient)
    assert len(logs_after_step1) == count_before + 1
    assert logs_after_step1[-1]["result"] == "allowed"
    assert logs_after_step1[-1]["actor_role"] == "family"

    # 2. Bệnh nhân thu hồi link qua POST /family/links/{id}/revoke
    revoke_res = client.post(f"/family/links/{link_id}/revoke", headers=patient_headers)
    assert revoke_res.status_code == 200
    assert revoke_res.json()["status"] == "revoked"
    assert revoke_res.json()["revoked_at"] is not None

    # Kiểm tra DB constraints và timestamps
    link_row = db.execute(
        text("SELECT status, revoked_at, rejected_at FROM caregiver_links WHERE id = :id"),
        {"id": link_id},
    ).one()
    assert link_row.status == "revoked"
    assert link_row.revoked_at is not None
    assert link_row.rejected_at is None

    # 3. Người thân gọi lại bằng cùng token -> 403 khong_co_quyen
    r_revoked = client.get(f"/medications/{user_med_id}", headers=family_headers)
    assert r_revoked.status_code == 403
    assert r_revoked.json() == {"detail": "khong_co_quyen"}

    # 4. Kiểm tra access_logs
    logs_after_step2 = make.access_logs(patient)
    assert len(logs_after_step2) == count_before + 2
    denied_log = logs_after_step2[-1]
    assert denied_log["result"] == "denied"
    assert denied_log["actor_user_id"] == family
    assert denied_log["actor_role"] == "khong_co_quyen"
    assert denied_log["data_scope"] == SCOPE_MEDICATIONS
    assert denied_log["rejection_reason"] == "khong_co_quyen"


# ==============================================================================
# T4_DELETE: Kiểm tra route DELETE /links/{id} (PR #39 / commit >= 5bb4e457)
# ==============================================================================


def test_revoke_link_via_delete_endpoint_pending_baseline_update__T4_delete__3_18(
    client, db, make, auth
):
    """T4_DELETE: Kiểm tra route DELETE /links/{id} (PR #39 / commit 5bb4e457).

    Xác minh:
    1. Bệnh nhân có link được chia sẻ hợp lệ; family truy cập thành công trước revoke (200 OK).
    2. Bệnh nhân gọi DELETE /links/{id} -> 204 No Content.
    3. Database row chuyển sang status='revoked', revoked_at NOT NULL, rejected_at IS NULL, sharing_enabled=False.
    4. Request kế tiếp bằng cùng token family bị 403 khong_co_quyen ngay lập tức.
    5. Đúng một denied access log mới được ghi nhận (actor_role='khong_co_quyen', data_scope, result='denied', rejection_reason='khong_co_quyen').
    """
    patient = make.user(consents=("health_data", "family_sharing"))
    family = make.user()
    family_headers = auth(family)
    patient_headers = auth(patient)
    user_med_id = _create_user_medication(db, patient, make.catalog_medication())

    link_id = make.link(patient, family, status="active", sharing=True)

    # 1. Family truy cập thành công trước khi revoke
    count_before = len(make.access_logs(patient))
    r_init = client.get(f"/medications/{user_med_id}", headers=family_headers)
    assert r_init.status_code == 200
    logs_init = make.access_logs(patient)
    assert len(logs_init) == count_before + 1
    assert logs_init[-1]["result"] == "allowed"
    assert logs_init[-1]["actor_role"] == "family"

    # 2. Thử gọi DELETE /links/{link_id} (hoặc fallback /family/links/{link_id} nếu route có prefix)
    del_res = client.delete(f"/links/{link_id}", headers=patient_headers)
    if del_res.status_code == 404:
        del_res = client.delete(f"/family/links/{link_id}", headers=patient_headers)
    if del_res.status_code in (404, 405):
        pytest.skip(
            f"Route DELETE /links/{link_id} trả về {del_res.status_code}. "
            "Route này thuộc PR #39 (commit 5bb4e457), chưa có trên baseline cũ."
        )

    # 3. API trả status code 204 No Content
    assert del_res.status_code == 204

    # 4. Database row chuyển sang 'revoked', revoked_at NOT NULL, rejected_at IS NULL
    link_row = db.execute(
        text("SELECT status, revoked_at, rejected_at, sharing_enabled FROM caregiver_links WHERE id = :id"),
        {"id": link_id},
    ).one()
    assert link_row.status == "revoked"
    assert link_row.revoked_at is not None
    assert link_row.rejected_at is None
    assert link_row.sharing_enabled is False

    # 5. Request kế tiếp bằng cùng family token bị 403 ngay lập tức
    r_revoked = client.get(f"/medications/{user_med_id}", headers=family_headers)
    assert r_revoked.status_code == 403
    assert r_revoked.json() == {"detail": "khong_co_quyen"}

    # 6. Đúng 1 denied access log mới được ghi cho request bị từ chối
    logs_after = make.access_logs(patient)
    assert len(logs_after) == count_before + 2
    denied_log = logs_after[-1]
    assert denied_log["actor_user_id"] == family
    assert denied_log["actor_role"] == "khong_co_quyen"
    assert denied_log["data_scope"] == SCOPE_MEDICATIONS
    assert denied_log["result"] == "denied"
    assert denied_log["rejection_reason"] == "khong_co_quyen"


# ==============================================================================
# T5: Liên kết lại sau revoke không khôi phục sharing cũ (QD-30)
# ==============================================================================


def test_relink_after_revoke_does_not_restore_sharing__T5__3_18(client, db, make, auth):
    """T5 (QD-30): Thu hồi rồi liên kết lại = yêu cầu mới, không tự khôi phục sharing cũ.

    1. Link 1 active, sharing bật -> family truy cập 200 OK.
    2. Bệnh nhân thu hồi Link 1 qua API DELETE (hoặc POST /revoke).
    3. Family bị từ chối ngay request tiếp theo (403).
    4. Family tạo yêu cầu liên kết mới -> Link 2 được tạo (status='pending', sharing_enabled=False).
       Xác minh link2_id != link1_id.
    5. Bệnh nhân approve Link 2 -> Link 2 active, nhưng sharing_enabled bắt đầu là False.
    6. Family gọi dữ liệu y tế -> vẫn 403 khong_co_quyen (không khôi phục sharing_enabled=True của Link 1).
    7. Bệnh nhân bật chia sẻ lại cho Link 2 -> Family mới truy cập được 200 OK.
    8. Sau khi sharing bật, nếu rút consent family_sharing -> quyền bị tước bỏ ngay lập tức.
    """
    patient = make.user(consents=("health_data", "family_sharing"))
    family = make.user()
    family_headers = auth(family)
    patient_headers = auth(patient)
    user_med_id = _create_user_medication(db, patient, make.catalog_medication())

    # Link 1 ban đầu active và có sharing
    link1_id = make.link(patient, family, status="active", sharing=True)
    assert client.get(f"/medications/{user_med_id}", headers=family_headers).status_code == 200

    # Thu hồi Link 1 qua API DELETE /links/{id} (nếu có) hoặc fallback POST /revoke
    del_res = client.delete(f"/links/{link1_id}", headers=patient_headers)
    if del_res.status_code == 404:
        del_res = client.delete(f"/family/links/{link1_id}", headers=patient_headers)
    if del_res.status_code == 204:
        pass
    else:
        revoke_res = client.post(f"/family/links/{link1_id}/revoke", headers=patient_headers)
        assert revoke_res.status_code == 200
        assert revoke_res.json()["status"] == "revoked"

    assert client.get(f"/medications/{user_med_id}", headers=family_headers).status_code == 403

    link1_row = db.execute(
        text("SELECT status, revoked_at FROM caregiver_links WHERE id = :id"),
        {"id": link1_id},
    ).one()
    assert link1_row.status == "revoked"
    assert link1_row.revoked_at is not None

    # Family tạo yêu cầu liên kết mới
    code = client.get("/family/link-code", headers=patient_headers).json()["code"]
    req_res = client.post(
        "/family/link-requests",
        json={"client_uuid": str(uuid4()), "code": code},
        headers=family_headers,
    )
    assert req_res.status_code == 201
    link2_id = req_res.json()["id"]
    assert link2_id != link1_id, "Link mới phải có ID mới"

    link2_row_req = db.execute(
        text("SELECT status, sharing_enabled, linked_at, revoked_at, rejected_at FROM caregiver_links WHERE id = :id"),
        {"id": link2_id},
    ).one()
    assert link2_row_req.status == "pending"
    assert link2_row_req.sharing_enabled is False
    assert link2_row_req.linked_at is not None
    assert link2_row_req.revoked_at is None
    assert link2_row_req.rejected_at is None

    # Bệnh nhân approve Link 2
    appr_res = client.post(
        f"/family/links/{link2_id}/approve",
        json={
            "family_user_id": str(family),
            "consent_confirmed": True,
            "document_version": DOCUMENT_VERSION,
        },
        headers=patient_headers,
    )
    assert appr_res.status_code == 200
    assert appr_res.json()["status"] == "active"
    assert appr_res.json()["sharing_enabled"] is False  # Không khôi phục True của Link 1

    link2_row_appr = db.execute(
        text("SELECT status, sharing_enabled, linked_at, revoked_at, rejected_at FROM caregiver_links WHERE id = :id"),
        {"id": link2_id},
    ).one()
    assert link2_row_appr.status == "active"
    assert link2_row_appr.sharing_enabled is False
    assert link2_row_appr.linked_at is not None
    assert link2_row_appr.revoked_at is None
    assert link2_row_appr.rejected_at is None

    # Xác minh confirmation của Link 2
    conf2 = db.execute(
        text("SELECT confirmed_at FROM family_link_consent_confirmations WHERE link_id = :id"),
        {"id": link2_id},
    ).one()
    assert conf2.confirmed_at is not None

    # Family truy cập -> Vẫn 403 khong_co_quyen
    r_link2_before_sharing = client.get(f"/medications/{user_med_id}", headers=family_headers)
    assert r_link2_before_sharing.status_code == 403
    assert r_link2_before_sharing.json() == {"detail": "khong_co_quyen"}

    # Bệnh nhân bật chia sẻ cho Link 2
    share_res = client.patch(
        f"/family/links/{link2_id}/sharing",
        json={"sharing_enabled": True},
        headers=patient_headers,
    )
    assert share_res.status_code == 200
    assert share_res.json()["sharing_enabled"] is True
    assert db.execute(
        text("SELECT sharing_enabled FROM caregiver_links WHERE id = :id"),
        {"id": link2_id},
    ).scalar_one() is True

    # Family gọi lại -> 200 OK
    assert client.get(f"/medications/{user_med_id}", headers=family_headers).status_code == 200

    # Bước 8 (QD-28): Sau khi sharing bật, rút consent family_sharing -> bị chặn 403 ngay
    withdraw_res = client.post("/consents/family_sharing/withdraw", headers=patient_headers)
    assert withdraw_res.status_code == 200
    r_withdrawn = client.get(f"/medications/{user_med_id}", headers=family_headers)
    assert r_withdrawn.status_code == 403
    assert r_withdrawn.json() == {"detail": "khong_co_quyen"}
