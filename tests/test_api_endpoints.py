"""Automated contract & TDD tests for DrugTime API Scaffold."""
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.mock_db import db
from app.core.rate_limit import redeem_rate_limiter, code_failure_tracker

client = TestClient(app)

@pytest.fixture(autouse=True)
def reset_db_state():
    """Reset database and rate limiters before each test."""
    db.reset()
    redeem_rate_limiter._failures.clear()
    code_failure_tracker.clear()


def test_health_check():
    res = client.get("/healthz")
    assert res.status_code == 200
    assert res.json()["status"] == "ok"

    res_v1 = client.get("/api/v1/health")
    assert res_v1.status_code == 200
    assert res_v1.json()["status"] == "ok"

def test_openapi_json_generation():
    res = client.get("/openapi.json")
    assert res.status_code == 200
    openapi = res.json()
    assert openapi["info"]["title"] == "DrugTime API"
    assert "/api/v1/users/me" in openapi["paths"]
    assert "/api/v1/dose-logs/batch-sync" in openapi["paths"]
    assert "/api/v1/caregivers/link-codes/redeem" in openapi["paths"]
    assert "/api/v1/admin/audit-logs" in openapi["paths"]

def test_user_profile_and_simple_mode():
    # Get profile
    res = client.get("/api/v1/users/me", headers={"Authorization": "Bearer usr-patient-1"})
    assert res.status_code == 200
    data = res.json()["data"]
    assert data["id"] == "usr-patient-1"
    assert data["che_do_nguoi_cao_tuoi"] is True

    # Update profile (toggle simple mode)
    patch_res = client.patch(
        "/api/v1/users/me",
        headers={"Authorization": "Bearer usr-patient-1"},
        json={"che_do_nguoi_cao_tuoi": False}
    )
    assert patch_res.status_code == 200
    assert patch_res.json()["data"]["che_do_nguoi_cao_tuoi"] is False

def test_consents_nd356():
    res = client.get("/api/v1/consents/me", headers={"Authorization": "Bearer usr-patient-1"})
    assert res.status_code == 200
    consents = res.json()["data"]
    assert len(consents) == 3
    purposes = {c["loai_dong_y"] for c in consents}
    assert purposes == {"health_data", "family_sharing", "ai_meal"}

    # Submit consent change
    post_res = client.post(
        "/api/v1/consents",
        headers={"Authorization": "Bearer usr-patient-1"},
        json={"loai_dong_y": "ai_meal", "trang_thai": "thu_hoi", "phien_ban_van_ban": "v1.1"}
    )
    assert post_res.status_code == 201
    assert post_res.json()["data"]["trang_thai"] == "thu_hoi"

def test_conditions_soft_delete():
    # List active conditions
    res = client.get("/api/v1/patients/usr-patient-1/conditions", headers={"Authorization": "Bearer usr-patient-1"})
    assert res.status_code == 200
    items = res.json()["data"]
    assert len(items) == 2

    # Add condition
    add_res = client.post(
        "/api/v1/patients/usr-patient-1/conditions",
        headers={"Authorization": "Bearer usr-patient-1"},
        json={"condition_id": 4} # Loét dạ dày
    )
    assert add_res.status_code == 201
    created_id = add_res.json()["data"]["id"]

    # Soft delete condition
    del_res = client.delete(
        f"/api/v1/patients/usr-patient-1/conditions/{created_id}",
        headers={"Authorization": "Bearer usr-patient-1"}
    )
    assert del_res.status_code == 200

    # Verify not in active list
    res_after = client.get("/api/v1/patients/usr-patient-1/conditions", headers={"Authorization": "Bearer usr-patient-1"})
    active_ids = [c["id"] for c in res_after.json()["data"]]
    assert created_id not in active_ids

def test_prescription_metadata_and_soft_delete():
    # Update metadata
    res = client.patch(
        "/api/v1/prescriptions/1",
        headers={"Authorization": "Bearer usr-patient-1"},
        json={"ngay_ke_don": "2026-09-20", "noi_ke_don": "Phòng khám Đa khoa Quốc tế"}
    )
    assert res.status_code == 200
    assert res.json()["data"]["noi_ke_don"] == "Phòng khám Đa khoa Quốc tế"

    # Soft delete user-medication
    del_med = client.delete(
        "/api/v1/user-medications/1",
        headers={"Authorization": "Bearer usr-patient-1"}
    )
    assert del_med.status_code == 200

    # Verify medication marked as archived in db
    med = next(m for m in db.user_medications if m["id"] == 1)
    assert med["trang_thai"] == "archived"

def test_idempotent_batch_dose_sync():
    req_body = {
        "logs": [
            {
                "client_uuid": "sync-uuid-1",
                "medication_schedule_id": 1,
                "thoi_gian_du_kien": "2026-09-21T08:00:00Z",
                "thoi_gian_thuc_uong": "2026-09-21T08:02:00Z",
                "trang_thai": "Đã uống"
            },
            {
                "client_uuid": "sync-uuid-2",
                "medication_schedule_id": 9999, # invalid schedule
                "thoi_gian_du_kien": "2026-09-21T18:00:00Z",
                "thoi_gian_thuc_uong": None,
                "trang_thai": "Bỏ lỡ"
            }
        ]
    }

    # First sync
    res = client.post("/api/v1/dose-logs/batch-sync", headers={"Authorization": "Bearer usr-patient-1"}, json=req_body)
    assert res.status_code == 200
    data = res.json()["data"]
    assert data["summary"]["synced"] == 1
    assert data["summary"]["duplicate"] == 0
    assert data["summary"]["error"] == 1
    assert data["results"][0]["status"] == "synced"
    assert data["results"][1]["status"] == "error"
    assert data["results"][1]["error_code"] == "SCHEDULE_NOT_FOUND"

    # Resync with same uuid (idempotency check)
    res_retry = client.post("/api/v1/dose-logs/batch-sync", headers={"Authorization": "Bearer usr-patient-1"}, json=req_body)
    assert res_retry.status_code == 200
    data_retry = res_retry.json()["data"]
    assert data_retry["summary"]["synced"] == 0
    assert data_retry["summary"]["duplicate"] == 1
    assert data_retry["results"][0]["status"] == "duplicate"

def test_caregiver_granular_read_write_rbac():
    # 1. Family member with WRITE permission (usr-family-1)
    write_res = client.post(
        "/api/v1/patients/usr-patient-1/conditions",
        headers={"Authorization": "Bearer usr-family-1"},
        json={"condition_id": 3}
    )
    assert write_res.status_code == 201

    # 2. Family member with READ-ONLY permission (usr-family-readonly)
    # Read allowed
    read_res = client.get(
        "/api/v1/patients/usr-patient-1/conditions",
        headers={"Authorization": "Bearer usr-family-readonly"}
    )
    assert read_res.status_code == 200

    # Write BLOCKED with 403 INSUFFICIENT_WRITE_PERMISSION
    blocked_write = client.post(
        "/api/v1/patients/usr-patient-1/conditions",
        headers={"Authorization": "Bearer usr-family-readonly"},
        json={"condition_id": 2}
    )
    assert blocked_write.status_code == 403
    assert blocked_write.json()["error"]["code"] == "INSUFFICIENT_WRITE_PERMISSION"

def test_link_code_brute_force_rate_limiting():
    # 5 wrong attempts should return 400
    for i in range(5):
        res = client.post(
            "/api/v1/caregivers/link-codes/redeem",
            headers={"Authorization": "Bearer usr-family-1"},
            json={"ma": f"WRONG-{i}"}
        )
        assert res.status_code == 400
        assert res.json()["error"]["code"] == "INVALID_LINK_CODE"

    # 6th attempt must be RATE LIMITED with 429
    blocked_res = client.post(
        "/api/v1/caregivers/link-codes/redeem",
        headers={"Authorization": "Bearer usr-family-1"},
        json={"ma": "DT-1234"} # Even with correct code, now locked
    )
    assert blocked_res.status_code == 429
    assert blocked_res.json()["error"]["code"] == "LINK_CODE_RATE_LIMITED"

def test_async_meal_suggestions():
    # Initiate async generation (202 Accepted)
    gen_res = client.post(
        "/api/v1/patients/usr-patient-1/meal-suggestions/generate",
        headers={"Authorization": "Bearer usr-patient-1"},
        json={"meal_type": "lunch"}
    )
    assert gen_res.status_code == 202
    job_id = gen_res.json()["data"]["job_id"]
    assert job_id.startswith("job-")

    # Poll status endpoint
    poll_res = client.get(
        f"/api/v1/patients/usr-patient-1/meal-suggestions/jobs/{job_id}",
        headers={"Authorization": "Bearer usr-patient-1"}
    )
    assert poll_res.status_code == 200
    poll_data = poll_res.json()["data"]
    assert poll_data["status"] == "completed"
    assert poll_data["result"]["bua_an"] == "Lunch"

def test_admin_audit_logs_pagination_and_auditability():
    # Trigger a patient read access to generate audit log
    client.get(
        "/api/v1/patients/usr-patient-1/prescriptions",
        headers={"Authorization": "Bearer usr-family-1"}
    )

    # Admin searches audit logs with pagination
    res = client.get(
        "/api/v1/admin/audit-logs?page=1&page_size=10",
        headers={"Authorization": "Bearer usr-admin-1"}
    )
    assert res.status_code == 200
    data = res.json()["data"]
    assert "items" in data
    assert "pagination" in data
    assert data["pagination"]["page"] == 1
    assert data["pagination"]["page_size"] == 10
    assert len(data["items"]) > 0

    # Non-admin access to admin audit log should be 403
    forbidden_res = client.get(
        "/api/v1/admin/audit-logs",
        headers={"Authorization": "Bearer usr-patient-1"}
    )
    assert forbidden_res.status_code == 403
    assert forbidden_res.json()["error"]["code"] == "ADMIN_REQUIRED"

def test_admin_override_reason_header_requirement():
    # 1. Admin attempts clinical write without X-Admin-Reason header -> 422
    no_reason_res = client.post(
        "/api/v1/patients/usr-patient-1/conditions",
        headers={"Authorization": "Bearer usr-admin-1"},
        json={"condition_id": 3}
    )
    assert no_reason_res.status_code == 422
    assert no_reason_res.json()["error"]["code"] == "ADMIN_OVERRIDE_REASON_REQUIRED"

    # 2. Admin attempts clinical write with too short X-Admin-Reason (< 10 chars) -> 422
    short_reason_res = client.post(
        "/api/v1/patients/usr-patient-1/conditions",
        headers={
            "Authorization": "Bearer usr-admin-1",
            "X-Admin-Reason": "Too short"
        },
        json={"condition_id": 3}
    )
    assert short_reason_res.status_code == 422
    assert short_reason_res.json()["error"]["code"] == "ADMIN_OVERRIDE_REASON_REQUIRED"

    # 3. Admin attempts clinical write with valid X-Admin-Reason (>= 10 chars) -> 201 Success
    from urllib.parse import quote
    valid_reason = "Can thiệp bổ sung bệnh lý nền theo hồ sơ chuyển viện Bạch Mai"
    ok_res = client.post(
        "/api/v1/patients/usr-patient-1/conditions",
        headers={
            "Authorization": "Bearer usr-admin-1",
            "X-Admin-Reason": quote(valid_reason)
        },
        json={"condition_id": 3}
    )
    assert ok_res.status_code == 201

    # Verify audit log recorded the decoded reason
    last_log = db.access_logs[-1]
    assert last_log["actor_role"] == "admin"
    assert last_log["ly_do_can_thiep"] == valid_reason

def test_caregiver_emergency_override_and_in_app_notification():
    from urllib.parse import quote
    # 1. Admin attempts to expand permissions -> 403 CANNOT_EXPAND_PERMISSIONS_AS_ADMIN
    expand_res = client.patch(
        "/api/v1/caregivers/1",
        headers={
            "Authorization": "Bearer usr-admin-1",
            "X-Admin-Reason": quote("Muốn cấp thêm quyền cho người thân này")
        },
        json={"cho_phep_chinh_sua": True}
    )
    assert expand_res.status_code == 403
    assert expand_res.json()["error"]["code"] == "CANNOT_EXPAND_PERMISSIONS_AS_ADMIN"

    # 2. Admin performs emergency revoke with valid reason
    revoke_reason = "Khẩn cấp: Nghi ngờ tài khoản người thân có hành vi lạm dụng đơn thuốc của người già"
    revoke_res = client.patch(
        "/api/v1/caregivers/1",
        headers={
            "Authorization": "Bearer usr-admin-1",
            "X-Admin-Reason": quote(revoke_reason)
        },
        json={"trang_thai": "revoked"}
    )
    assert revoke_res.status_code == 200
    assert revoke_res.json()["data"]["trang_thai"] == "revoked"

    # Verify emergency audit entry and Four-Eyes deadline
    last_audit = next(l for l in reversed(db.access_logs) if l.get("action") == "REVOKE_CAREGIVER")
    assert last_audit["is_emergency_override"] is True
    assert last_audit["review_status"] == "pending_post_review"
    assert last_audit["review_deadline"] is not None

    # Verify in-app notification sent to patient
    patient_notifs = [n for n in db.notifications if n["user_id"] == "usr-patient-1"]
    assert any("thu hồi liên kết" in n["noi_dung"] and revoke_reason in n["noi_dung"] for n in patient_notifs)

def test_four_eyes_post_review_three_states_and_guardrails():
    from urllib.parse import quote
    # 1. Trigger an emergency override by Admin A (usr-admin-1)
    revoke_res = client.patch(
        "/api/v1/caregivers/1",
        headers={
            "Authorization": "Bearer usr-admin-1",
            "X-Admin-Reason": quote("Thu hồi khẩn cấp liên kết theo yêu cầu khẩn")
        },
        json={"trang_thai": "revoked"}
    )
    assert revoke_res.status_code == 200
    target_audit_log = next(l for l in reversed(db.access_logs) if l.get("action") == "REVOKE_CAREGIVER")
    audit_id = target_audit_log["id"]

    # Guardrail 1: Non-admin caller -> 403
    non_admin_res = client.post(
        f"/api/v1/admin/audit-logs/{audit_id}/post-review",
        headers={"Authorization": "Bearer usr-family-1"},
        json={"decision": "valid", "review_note": "Người thân kiểm tra"}
    )
    assert non_admin_res.status_code == 403

    # Guardrail 2: Admin A cannot review own action -> 403 CANNOT_REVIEW_OWN_ACTION
    self_review_res = client.post(
        f"/api/v1/admin/audit-logs/{audit_id}/post-review",
        headers={"Authorization": "Bearer usr-admin-1"},
        json={"decision": "valid", "review_note": "Tự tôi xác nhận hành động của tôi đúng"}
    )
    assert self_review_res.status_code == 403
    assert self_review_res.json()["error"]["code"] == "CANNOT_REVIEW_OWN_ACTION"

    # Guardrail 3: Admin B reviews a non-emergency log -> 409 REVIEW_NOT_REQUIRED
    # Trigger a normal read log
    client.get("/api/v1/patients/usr-patient-1/prescriptions", headers={"Authorization": "Bearer usr-patient-1"})
    normal_log = db.access_logs[-1]
    not_req_res = client.post(
        f"/api/v1/admin/audit-logs/{normal_log['id']}/post-review",
        headers={"Authorization": "Bearer usr-admin-2"},
        json={"decision": "valid", "review_note": "Kiểm tra log bình thường"}
    )
    assert not_req_res.status_code == 409
    assert not_req_res.json()["error"]["code"] == "REVIEW_NOT_REQUIRED"

    # 2. Admin B (usr-admin-2) completes review with decision: 'valid'
    valid_review_note = "Đã kiểm tra yêu cầu bảo vệ bệnh nhân và hồ sơ liên quan."
    review_res = client.post(
        f"/api/v1/admin/audit-logs/{audit_id}/post-review",
        headers={"Authorization": "Bearer usr-admin-2"},
        json={"decision": "valid", "review_note": valid_review_note}
    )
    assert review_res.status_code == 200
    assert review_res.json()["data"]["review_status"] == "reviewed_valid"

    # Verify target record updated
    updated_target = next(l for l in db.access_logs if l["id"] == audit_id)
    assert updated_target["review_status"] == "reviewed_valid"
    assert updated_target["reviewer_user_id"] == "usr-admin-2"

    # Verify audit event generated for the review action itself
    review_event = db.access_logs[-1]
    assert review_event["action"] == "POST_REVIEW"
    assert review_event["target_audit_log_id"] == audit_id
    assert review_event["actor_user_id"] == "usr-admin-2"
    assert review_event["review_decision"] == "valid"

    # Guardrail 4: Attempting to review already completed log -> 409 REVIEW_ALREADY_COMPLETED
    retry_review = client.post(
        f"/api/v1/admin/audit-logs/{audit_id}/post-review",
        headers={"Authorization": "Bearer usr-admin-2"},
        json={"decision": "valid", "review_note": "Thử hậu kiểm lại lần nữa"}
    )
    assert retry_review.status_code == 409
    assert retry_review.json()["error"]["code"] == "REVIEW_ALREADY_COMPLETED"

def test_four_eyes_post_review_invalid_decision_compliance_flag():
    from urllib.parse import quote
    # Emergency override by Admin A on link #2
    client.patch(
        "/api/v1/caregivers/2",
        headers={
            "Authorization": "Bearer usr-admin-1",
            "X-Admin-Reason": quote("Nghi ngờ vi phạm can thiệp liều dùng")
        },
        json={"trang_thai": "revoked"}
    )
    target_audit_log = next(l for l in reversed(db.access_logs) if l.get("action") == "REVOKE_CAREGIVER")
    audit_id = target_audit_log["id"]

    # Admin B marks decision: 'invalid'
    invalid_note = "Thu hồi không đúng quy trình, chứng cứ không thuyết phục"
    review_res = client.post(
        f"/api/v1/admin/audit-logs/{audit_id}/post-review",
        headers={"Authorization": "Bearer usr-admin-2"},
        json={"decision": "invalid", "review_note": invalid_note}
    )
    assert review_res.status_code == 200
    assert review_res.json()["data"]["review_status"] == "reviewed_invalid"

    # Check compliance flag and that caregiver link was NOT automatically restored
    updated_target = next(l for l in db.access_logs if l["id"] == audit_id)
    assert updated_target["review_status"] == "reviewed_invalid"
    assert "COMPLIANCE_REVIEW_REQUIRED" in updated_target["compliance_flags"]

    link2 = next(l for l in db.caregiver_links if l["id"] == 2)
    assert link2["trang_thai"] == "revoked" # Not automatically restored

    # Notification sent to compliance
    compliance_notifs = [n for n in db.notifications if n.get("loai") == "canh_bao_compliance"]
    assert len(compliance_notifs) > 0

def test_link_code_multi_use_and_global_invalidation():
    # Patient creates a link code
    create_res = client.post("/api/v1/caregivers/link-codes", headers={"Authorization": "Bearer usr-patient-1"})
    assert create_res.status_code == 201
    code = create_res.json()["data"]["ma"]

    # 1. Family member 1 redeems code -> Success (Multi-use)
    redeem1 = client.post(
        "/api/v1/caregivers/link-codes/redeem",
        headers={"Authorization": "Bearer usr-family-1"},
        json={"ma": code}
    )
    assert redeem1.status_code == 200

    # 2. Family member 2 redeems SAME code -> Success (Multi-use within 15 min)
    redeem2 = client.post(
        "/api/v1/caregivers/link-codes/redeem",
        headers={"Authorization": "Bearer usr-family-readonly"},
        json={"ma": code}
    )
    assert redeem2.status_code == 200

    # 3. Distributed attack: 10 wrong attempts on a code invalidate it
    fake_code = "DT-9999"
    for _ in range(10):
        # Reset caller limiter so we simulate different callers/IPs
        redeem_rate_limiter._failures.clear()
        client.post(
            "/api/v1/caregivers/link-codes/redeem",
            headers={"Authorization": "Bearer usr-family-1"},
            json={"ma": fake_code}
        )

    # 11th attempt on fake_code triggers LINK_CODE_INVALIDATED
    redeem_rate_limiter._failures.clear()
    blocked_res = client.post(
        "/api/v1/caregivers/link-codes/redeem",
        headers={"Authorization": "Bearer usr-family-1"},
        json={"ma": fake_code}
    )
    assert blocked_res.status_code == 400
    assert blocked_res.json()["error"]["code"] == "LINK_CODE_INVALIDATED"

def test_ocr_upload_read_permission_and_file_constraints():
    # 1. Family member with READ-ONLY permission can call OCR preview
    file_payload = ("test_rx.jpg", b"fake image bytes content", "image/jpeg")
    ok_res = client.post(
        "/api/v1/patients/usr-patient-1/prescriptions/ocr-upload",
        headers={"Authorization": "Bearer usr-family-readonly"},
        files={"file": file_payload}
    )
    assert ok_res.status_code == 200
    assert "scanned_text" in ok_res.json()["data"]

    # 2. Invalid MIME type (e.g. text/plain) -> 422
    bad_type_res = client.post(
        "/api/v1/patients/usr-patient-1/prescriptions/ocr-upload",
        headers={"Authorization": "Bearer usr-patient-1"},
        files={"file": ("malicious.exe", b"MZ...", "application/x-msdownload")}
    )
    assert bad_type_res.status_code == 422
    assert bad_type_res.json()["error"]["code"] == "INVALID_FILE_TYPE"

    # 3. File exceeding 10MB -> 422
    oversized_bytes = b"0" * (10 * 1024 * 1024 + 10)
    oversized_res = client.post(
        "/api/v1/patients/usr-patient-1/prescriptions/ocr-upload",
        headers={"Authorization": "Bearer usr-patient-1"},
        files={"file": ("huge_photo.jpg", oversized_bytes, "image/jpeg")}
    )
    assert oversized_res.status_code == 422
    assert oversized_res.json()["error"]["code"] == "FILE_TOO_LARGE"

def test_admin_rule_change_logs_and_async_data_export():
    # 1. Admin reads rule change logs
    rule_res = client.get(
        "/api/v1/admin/rule-change-logs?page=1&page_size=10",
        headers={"Authorization": "Bearer usr-admin-1"}
    )
    assert rule_res.status_code == 200
    data = rule_res.json()["data"]
    assert "items" in data
    assert "pagination" in data
    assert len(data["items"]) > 0

    # 2. User initiates async data export (202 Accepted)
    export_res = client.post(
        "/api/v1/users/me/data-export",
        headers={"Authorization": "Bearer usr-patient-1"},
        json={"format": "json"}
    )
    assert export_res.status_code == 202
    job_id = export_res.json()["data"]["job_id"]
    assert job_id.startswith("export-")

    # 3. User polls export job status (200 OK)
    poll_res = client.get(
        f"/api/v1/users/me/data-export/jobs/{job_id}",
        headers={"Authorization": "Bearer usr-patient-1"}
    )
    assert poll_res.status_code == 200
    poll_data = poll_res.json()["data"]
    assert poll_data["job_id"] == job_id
    assert poll_data["download_url"] is not None

