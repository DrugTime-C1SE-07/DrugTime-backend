"""Audit của POST /patients/{patient_id}/interaction-checks sau khi sửa ở task 4.05 (AC21, G15).

Hành vi cho/từ chối của endpoint 4.02 không đổi; chỉ thêm dòng access_logs khi người bệnh tự gọi.
"""

import pytest
from sqlalchemy import text

SCOPE = "canh_bao_tuong_tac"
DDI_RULES = "/admin/drug-interactions"


def _log(actor, role, result, reason=None):
    return {
        "actor_user_id": actor,
        "actor_role": role,
        "data_scope": SCOPE,
        "result": result,
        "rejection_reason": reason,
    }


def _check(client, auth, caller, patient):
    return client.post(f"/patients/{patient}/interaction-checks", json={}, headers=auth(caller))


def test_self_check_logged_allowed__AC21(client, make, auth, scheduled_body):
    p = make.user()
    client.post("/medications", json=scheduled_body(make.catalog_medication()), headers=auth(p))
    r = _check(client, auth, p, p)
    assert r.status_code == 200, r.text
    assert r.json()["disclaimer"]
    assert make.access_logs(p) == [_log(p, "patient", "allowed")]


def test_self_revoked_consent_403_logged_denied__AC21(client, make, auth):
    p = make.user()
    make.revoke_consent(p, "health_data")
    r = _check(client, auth, p, p)
    assert r.status_code == 403 and r.json() == {"detail": "consent_revoked"}
    assert make.access_logs(p) == [_log(p, "patient", "denied", "consent_revoked")]


@pytest.mark.parametrize("who", ["stranger", "admin"])
def test_stranger_and_admin_still_denied__AC21(client, make, auth, who):
    p = make.user()
    caller = make.user(admin=who == "admin")
    r = _check(client, auth, caller, p)
    assert r.status_code == 403 and r.json() == {"detail": "khong_co_quyen"}
    role = "admin" if who == "admin" else "khong_co_quyen"
    assert make.access_logs(p) == [_log(caller, role, "denied", "khong_co_quyen")]


def test_family_still_allowed_and_logged__AC21(client, make, auth):
    p = make.user()
    family = make.family_of(p)
    r = _check(client, auth, family, p)
    assert r.status_code == 200, r.text
    assert make.access_logs(p) == [_log(family, "family", "allowed")]


@pytest.mark.parametrize("who", ["patient", "family"])
def test_commit_failure_returns_no_data_and_no_log__AC24(client, make, auth, scheduled_body, who):
    """Task 4.05 (AC24): trước khi sửa, route này trả 200 kèm dữ liệu khi commit lỗi
    (evidence/review-commit-failure.log). Giờ commit xong mới trả response."""
    from unittest.mock import patch

    from fastapi.testclient import TestClient
    from sqlalchemy.engine.base import RootTransaction

    from drugtime.main import create_app

    p = make.user()
    r = client.post("/medications", json=scheduled_body(make.catalog_medication()), headers=auth(p))
    assert r.status_code == 201, r.text
    caller = p if who == "patient" else make.family_of(p)
    failing_client = TestClient(create_app(), raise_server_exceptions=False)

    def failing_commit(self):
        raise RuntimeError("simulated commit failure")

    with patch.object(RootTransaction, "commit", failing_commit):
        r = failing_client.post(
            f"/patients/{p}/interaction-checks", json={}, headers=auth(caller)
        )
    assert r.status_code == 500
    assert "disclaimer" not in r.text and "insufficient_data_medications" not in r.text
    assert make.access_logs(p) == []


@pytest.mark.parametrize("revoke", ["health_data", "family_sharing", "sharing_off", "unlink"])
def test_family_denied_right_after_revoke__TC_BE_01_04(
    client, db, make, auth, scheduled_body, revoke
):
    """Task 5.22 (PB27): thu hồi consent/tắt chia sẻ/hủy liên kết có hiệu lực ngay ở request sau."""
    p = make.user()
    med_id = make.catalog_medication()
    r_add = client.post("/medications", json=scheduled_body(med_id), headers=auth(p))
    assert r_add.status_code == 201, r_add.text
    family = make.family_of(p)
    assert _check(client, auth, family, p).status_code == 200

    if revoke in ("health_data", "family_sharing"):
        make.revoke_consent(p, revoke)
    else:
        clause = (
            "sharing_enabled = false"
            if revoke == "sharing_off"
            else "status = 'revoked', revoked_at = now()"
        )
        db.execute(
            text(
                f"UPDATE caregiver_links SET {clause} "
                "WHERE patient_user_id = :p AND family_user_id = :f"
            ),
            {"p": p, "f": family},
        )

    r = _check(client, auth, family, p)
    assert r.status_code == 403 and r.json() == {"detail": "khong_co_quyen"}
    assert "disclaimer" not in r.text and "interactions" not in r.text
    assert make.access_logs(p) == [
        _log(family, "family", "allowed"),
        _log(family, "khong_co_quyen", "denied", "khong_co_quyen"),
    ]


def test_family_swaps_patient_id_denied__TC_BE_05(client, make, auth, scheduled_body):
    """Task 5.22 (PB27): người thân của P không được tráo patient_id sang người bệnh khác."""
    p = make.user()
    other = make.user()
    client.post("/medications", json=scheduled_body(make.catalog_medication()), headers=auth(other))
    family = make.family_of(p)

    r = _check(client, auth, family, other)
    assert r.status_code == 403 and r.json() == {"detail": "khong_co_quyen"}
    assert "disclaimer" not in r.text and "interactions" not in r.text
    assert make.access_logs(other) == [_log(family, "khong_co_quyen", "denied", "khong_co_quyen")]
    assert make.access_logs(p) == []


def test_family_denied_when_patient_pending_deletion__TC_BE_06(
    client, db, make, auth, scheduled_body
):
    """Task 5.22 (PB27): tài khoản người bệnh đang chờ xóa -> FM bị 403 khong_co_quyen + audit."""
    p = make.user()
    client.post("/medications", json=scheduled_body(make.catalog_medication()), headers=auth(p))
    family = make.family_of(p)
    db.execute(
        text(
            "INSERT INTO data_deletion_requests (user_id, requested_at, scheduled_deletion_at) "
            "VALUES (:u, now(), now() + interval '720 hours')"
        ),
        {"u": p},
    )

    r = _check(client, auth, family, p)
    assert r.status_code == 403 and r.json() == {"detail": "khong_co_quyen"}
    assert "disclaimer" not in r.text and "interactions" not in r.text
    assert make.access_logs(p) == [_log(family, "family", "denied", "khong_co_quyen")]


def test_family_response_parity_with_patient__TC_BE_07_08(
    client, make, auth, admin_auth, scheduled_body
):
    """Task 5.22 (PB27): nội dung tương tác thuốc-thuốc (severity, handling_type,
    insufficient_data_medications, medication_ids filter, disclaimer) trả cho FM khớp Patient."""
    _, admin_h = admin_auth
    p = make.user()
    family = make.family_of(p)

    ing_a, ing_b = make.ingredient(), make.ingredient()
    rule_resp = client.post(
        DDI_RULES,
        json={
            "ingredient_a_id": ing_a,
            "ingredient_b_id": ing_b,
            "interaction_type": "chong_chi_dinh",
            "severity_level": 4,
            "handling_type": "tranh_phoi_hop",
            "description": "Nguy cơ chảy máu nghiêm trọng.",
            "source": "QĐ 5948/QĐ-BYT",
        },
        headers=admin_h,
    )
    assert rule_resp.status_code == 201, rule_resp.text

    med_a = make.medication_with([ing_a])
    med_b = make.medication_with([ing_b])
    med_insuff = make.catalog_medication(with_ingredient=False)
    for mid in (med_a, med_b, med_insuff):
        r_add = client.post("/medications", json=scheduled_body(mid), headers=auth(p))
        assert r_add.status_code == 201, r_add.text

    bodies = [
        {},
        {"medication_ids": [med_a, med_b]},
        {"medication_ids": [med_a], "candidate_medication_id": med_b},
    ]
    for payload in bodies:
        r_patient = client.post(f"/patients/{p}/interaction-checks", json=payload, headers=auth(p))
        r_family = client.post(
            f"/patients/{p}/interaction-checks", json=payload, headers=auth(family)
        )
        assert r_patient.status_code == 200, r_patient.text
        assert r_family.status_code == 200, r_family.text
        assert r_family.json() == r_patient.json()
        data = r_family.json()
        assert data["status"] == "co_tuong_tac"
        assert data["disclaimer"]
        assert len(data["interactions"]) == 1
        assert data["interactions"][0]["severity_level"] == 4
        assert data["interactions"][0]["handling_type"] == "tranh_phoi_hop"
        if payload == {}:
            assert len(data["insufficient_data_medications"]) == 1
        else:
            assert data["insufficient_data_medications"] == []

    fm_logs = [row for row in make.access_logs(p) if row["actor_user_id"] == family]
    assert fm_logs == [_log(family, "family", "allowed")] * len(bodies)
