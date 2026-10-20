"""Kiểm tra tích hợp phân quyền y tế qua PEP, thu hồi quyền tức thì và truy vấn người thân (task 3.16).

Bao phủ kịch bản I10, I11, I12 theo AC6, AC7, AC10, AC11.
"""

from uuid import UUID

import pytest
from sqlalchemy import text

from drugtime.modules.family import api as family_api
from drugtime.shared.db import unit_of_work

SCOPE = "danh_sach_thuoc"


def _log(actor: UUID, role: str, result: str, reason: str | None = None) -> dict:
    return {
        "actor_user_id": actor,
        "actor_role": role,
        "data_scope": SCOPE,
        "result": result,
        "rejection_reason": reason,
    }


def _create_user_medication(db, patient_id: UUID, med_id: int) -> int:
    rx_id = db.execute(
        text("INSERT INTO prescriptions (user_id, entry_source) VALUES (:u, 'mac_dinh') RETURNING id"),
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
# I10: Family PEP matrix and write denied (AC6, AC10)
# ==============================================================================


def test_approved_link_with_sharing_off_gets_403_and_denied_log__AC6(client, db, make, auth):
    """AC6: Sau khi approve, sharing_enabled mặc định là False;

    family đọc dữ liệu y tế bị 403 và có denied access_logs.
    """
    patient = make.user(consents=("health_data", "family_sharing"))
    family = make.user()
    # Tạo link active có bằng chứng evidence nhưng sharing_enabled=False
    link_id = make.link(patient, family, status="active", sharing=False)
    med_id = make.catalog_medication()
    user_med_id = _create_user_medication(db, patient, med_id)

    r = client.get(f"/medications/{user_med_id}", headers=auth(family))
    assert r.status_code == 403
    assert r.json() == {"detail": "khong_co_quyen"}

    logs = make.access_logs(patient)
    assert len(logs) == 1
    assert logs[0]["result"] == "denied"
    assert logs[0]["actor_user_id"] == family


def test_approved_link_with_sharing_on_gets_200_and_allowed_log__AC6(client, db, make, auth):
    """AC6: Link active có evidence VÀ sharing_enabled=True (PB18):

    family đọc dữ liệu y tế thành công 200 và có allowed access_logs.
    """
    patient = make.user(consents=("health_data", "family_sharing"))
    family = make.user()
    # Tạo link active có bằng chứng evidence và sharing_enabled=True
    link_id = make.link(patient, family, status="active", sharing=True)
    med_id = make.catalog_medication()
    user_med_id = _create_user_medication(db, patient, med_id)

    r = client.get(f"/medications/{user_med_id}", headers=auth(family))
    assert r.status_code == 200

    logs = make.access_logs(patient)
    assert len(logs) == 1
    assert logs[0]["result"] == "allowed"
    assert logs[0]["actor_user_id"] == family
    assert logs[0]["actor_role"] == "family"


def test_family_cannot_write_medications__AC6(client, db, make, auth):
    """AC6 / QD-27: Người thân có quyền xem nhưng KHÔNG có quyền ghi thay;

    PATCH /medications bị 403 và có denied log.
    """
    patient = make.user(consents=("health_data", "family_sharing"))
    family = make.user()
    make.link(patient, family, status="active", sharing=True)
    med_id = make.catalog_medication()
    user_med_id = _create_user_medication(db, patient, med_id)

    r = client.patch(
        f"/medications/{user_med_id}",
        json={"stopped": True},
        headers=auth(family),
    )
    assert r.status_code == 403
    assert r.json() == {"detail": "khong_co_quyen"}

    logs = make.access_logs(patient)
    assert any(log["result"] == "denied" for log in logs)


def test_family_cannot_read_other_patient_medication__AC6_AC10(client, db, make, auth):
    """AC6, AC10: Người thân của P không được đọc thuốc của người bệnh Q khác;

    bị 403 và ghi denied log cho Q.
    """
    p1 = make.user(consents=("health_data", "family_sharing"))
    p2 = make.user(consents=("health_data", "family_sharing"))
    family = make.user()
    make.link(p1, family, status="active", sharing=True)

    med_id = make.catalog_medication()
    user_med2_id = _create_user_medication(db, p2, med_id)

    r = client.get(f"/medications/{user_med2_id}", headers=auth(family))
    assert r.status_code == 403
    assert r.json() == {"detail": "khong_co_quyen"}

    logs_p2 = make.access_logs(p2)
    assert len(logs_p2) == 1
    assert logs_p2[0]["result"] == "denied"
    assert logs_p2[0]["actor_user_id"] == family


# ==============================================================================
# I11: Revocation takes effect immediately on next request with same JWT (AC7)
# ==============================================================================


@pytest.mark.parametrize("revocation_type", ["revoke_consent", "revoke_link"])
def test_revocation_takes_effect_immediately_same_jwt__AC7(
    client, db, make, auth, revocation_type
):
    """AC7: Đang truy cập y tế hợp lệ 200, sau khi rút consent hoặc hủy link:

    ngay request tiếp theo với cùng JWT token sẽ bị 403 và ghi denied log.
    Không cache quyền truy cập ở API hay JWT.
    """
    patient = make.user(consents=("health_data", "family_sharing"))
    family = make.user()
    link_id = make.link(patient, family, status="active", sharing=True)
    med_id = make.catalog_medication()
    user_med_id = _create_user_medication(db, patient, med_id)

    token_headers = auth(family)

    # 1. Lần 1: truy cập thành công 200
    r1 = client.get(f"/medications/{user_med_id}", headers=token_headers)
    assert r1.status_code == 200

    # 2. Bệnh nhân rút consent hoặc hủy liên kết
    if revocation_type == "revoke_consent":
        make.revoke_consent(patient, "family_sharing")
    else:
        db.execute(
            text(
                "UPDATE caregiver_links SET status = 'revoked', revoked_at = now() "
                "WHERE id = :id"
            ),
            {"id": link_id},
        )

    # 3. Lần 2: cùng token JWT gửi lại ngay lập tức -> 403 khong_co_quyen
    r2 = client.get(f"/medications/{user_med_id}", headers=token_headers)
    assert r2.status_code == 403
    assert r2.json() == {"detail": "khong_co_quyen"}

    # Khẳng định access_logs ghi nhận 1 allowed và 1 denied
    logs = make.access_logs(patient)
    results = [l["result"] for l in logs]
    assert results == ["allowed", "denied"]


# ==============================================================================
# I12: Worker recipients logic: excludes legacy and missing evidence (AC6, 7, 10, 11)
# ==============================================================================


def test_sharing_family_ids_excludes_legacy_and_revoked__AC6_AC7_AC11(db, make):
    """AC6, AC7, AC11: sharing_family_ids chỉ trả về family có active link + sharing=true

    + có evidence consent hợp lệ. Loại trừ link legacy không có evidence,
    link revoked, và link sharing=false.
    """
    patient = make.user(consents=("health_data", "family_sharing"))

    # 1. Hợp lệ: active, sharing=true, có evidence
    f_valid = make.user()
    make.link(patient, f_valid, status="active", sharing=True)

    # 2. Không có evidence: active legacy, sharing=true
    f_legacy = make.user()
    make.link(patient, f_legacy, status="active", sharing=True, legacy=True)

    # 3. Có evidence nhưng sharing=false
    f_nosharing = make.user()
    make.link(patient, f_nosharing, status="active", sharing=False)

    # 4. Link revoked
    f_revoked = make.user()
    make.link(patient, f_revoked, status="revoked", sharing=True, legacy=True)

    with unit_of_work() as uow:
        recipients = family_api.sharing_family_ids(uow, patient)

    assert f_valid in recipients
    assert f_legacy not in recipients
    assert f_nosharing not in recipients
    assert f_revoked not in recipients
