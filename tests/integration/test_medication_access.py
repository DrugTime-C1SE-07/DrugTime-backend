"""Phân quyền /medications qua PEP của access (task 2.01, AC14, AC15, AC17, wf-health-endpoint).

Mỗi ca kiểm cả response lẫn dòng access_logs. Truy cập của chính chủ không ghi log (quy tắc
có sẵn của access: log_role None).
"""

import pytest
from sqlalchemy import text

SCOPE = "danh_sach_thuoc"


@pytest.fixture
def setup(make, client, auth, scheduled_body):
    """Người bệnh P với một thuốc X đang dùng."""
    patient = make.user()
    body = scheduled_body(make.catalog_medication(), stock_quantity=10)
    r = client.post("/medications", json=body, headers=auth(patient))
    assert r.status_code == 201, r.text
    return patient, r.json()


def _snapshot(db, med_id):
    med = db.execute(
        text(
            "SELECT quantity_per_dose, stock_quantity, ended_at FROM user_medications WHERE id = :i"
        ),
        {"i": med_id},
    ).one()
    schedules = db.execute(
        text(
            "SELECT id, ended_at FROM medication_schedules "
            "WHERE user_medication_id = :i ORDER BY id"
        ),
        {"i": med_id},
    ).all()
    return med, schedules


def _log(actor, role, result, reason=None):
    return {
        "actor_user_id": actor,
        "actor_role": role,
        "data_scope": SCOPE,
        "result": result,
        "rejection_reason": reason,
    }


def test_patient_reads_and_writes_own_without_log(client, make, auth, setup):
    patient, med = setup
    assert client.get(f"/medications/{med['id']}", headers=auth(patient)).status_code == 200
    r = client.patch(f"/medications/{med['id']}", json={"stock_quantity": 9}, headers=auth(patient))
    assert r.status_code == 200
    assert make.access_logs(patient) == []


@pytest.mark.parametrize("method", ["get", "patch"])
def test_unlinked_user_get_and_patch_403_denied_logged__AC14(client, db, make, auth, setup, method):
    patient, med = setup
    stranger = make.user()
    before = _snapshot(db, med["id"])
    kwargs = {"json": {"stopped": True}} if method == "patch" else {}
    r = client.request(method, f"/medications/{med['id']}", headers=auth(stranger), **kwargs)
    assert r.status_code == 403 and r.json() == {"detail": "khong_co_quyen"}
    assert "medication" not in r.text
    assert make.access_logs(patient) == [
        _log(stranger, "khong_co_quyen", "denied", "khong_co_quyen")
    ]
    assert _snapshot(db, med["id"]) == before


def test_linked_family_reads_allowed_logged_but_cannot_write__AC15(client, db, make, auth, setup):
    patient, med = setup
    family = make.family_of(patient)
    r = client.get(f"/medications/{med['id']}", headers=auth(family))
    assert r.status_code == 200 and r.json() == med

    before = _snapshot(db, med["id"])
    r = client.patch(f"/medications/{med['id']}", json={"stopped": True}, headers=auth(family))
    assert r.status_code == 403 and r.json() == {"detail": "khong_co_quyen"}
    assert _snapshot(db, med["id"]) == before
    assert make.access_logs(patient) == [
        _log(family, "family", "allowed"),
        _log(family, "family", "denied", "khong_co_quyen"),
    ]


def test_admin_reads_but_cannot_write__AC15(client, db, make, auth, setup):
    patient, med = setup
    admin = make.user(admin=True)
    assert client.get(f"/medications/{med['id']}", headers=auth(admin)).status_code == 200
    before = _snapshot(db, med["id"])
    r = client.patch(
        f"/medications/{med['id']}", json={"quantity_per_dose": 3}, headers=auth(admin)
    )
    assert r.status_code == 403
    assert _snapshot(db, med["id"]) == before
    assert make.access_logs(patient) == [
        _log(admin, "admin", "allowed"),
        _log(admin, "admin", "denied", "khong_co_quyen"),
    ]


@pytest.mark.parametrize("missing", ["sharing_off", "health_data", "family_sharing"])
def test_family_missing_purpose_consent_or_sharing_off_403(client, make, auth, setup, missing):
    patient, med = setup
    family = make.family_of(patient, sharing=missing != "sharing_off")
    if missing != "sharing_off":
        make.revoke_consent(patient, missing)
    r = client.get(f"/medications/{med['id']}", headers=auth(family))
    assert r.status_code == 403
    assert make.access_logs(patient) == [_log(family, "khong_co_quyen", "denied", "khong_co_quyen")]


@pytest.mark.parametrize("revoke", ["link", "consent"])
def test_revoke_then_immediate_request_403(client, db, make, auth, setup, revoke):
    patient, med = setup
    family = make.family_of(patient)
    assert client.get(f"/medications/{med['id']}", headers=auth(family)).status_code == 200
    if revoke == "link":
        db.execute(
            text(
                "UPDATE caregiver_links SET status = 'revoked', revoked_at = now() "
                "WHERE patient_user_id = :p AND family_user_id = :f"
            ),
            {"p": patient, "f": family},
        )
    else:
        make.revoke_consent(patient, "family_sharing")
    r = client.get(f"/medications/{med['id']}", headers=auth(family))
    assert r.status_code == 403
    assert [log["result"] for log in make.access_logs(patient)] == ["allowed", "denied"]


def test_family_cannot_access_other_patient(client, make, auth, setup, scheduled_body):
    """Người thân hợp lệ của P đổi id sang thuốc của người bệnh khác Q."""
    patient, _ = setup
    family = make.family_of(patient)
    other = make.user()
    r = client.post(
        "/medications",
        json=scheduled_body(make.catalog_medication()),
        headers=auth(other),
    )
    other_med = r.json()
    r = client.get(f"/medications/{other_med['id']}", headers=auth(family))
    assert r.status_code == 403
    assert make.access_logs(other) == [_log(family, "khong_co_quyen", "denied", "khong_co_quyen")]


def test_self_revoked_consent_cannot_create__AC17(client, make, auth, scheduled_body):
    patient = make.user()
    make.revoke_consent(patient, "health_data")
    r = client.post(
        "/medications", json=scheduled_body(make.catalog_medication()), headers=auth(patient)
    )
    assert r.status_code == 403 and r.json() == {"detail": "consent_revoked"}
    assert make.counts(patient) == {"meds": 0, "schedules": 0, "prescriptions": 0}
    assert make.access_logs(patient) == []


def test_self_revoked_consent_cannot_read_or_patch(client, db, make, auth, setup):
    patient, med = setup
    make.revoke_consent(patient, "health_data")
    assert client.get(f"/medications/{med['id']}", headers=auth(patient)).status_code == 403
    before = _snapshot(db, med["id"])
    r = client.patch(f"/medications/{med['id']}", json={"stopped": True}, headers=auth(patient))
    assert r.status_code == 403 and r.json() == {"detail": "consent_revoked"}
    assert _snapshot(db, med["id"]) == before


def test_allowed_log_failure_fails_request(client, make, auth, setup, monkeypatch):
    """Ghi access log thất bại → request thất bại, không trả dữ liệu (fail-closed)."""
    from fastapi.testclient import TestClient

    from drugtime.main import create_app
    from drugtime.modules.access.adapters.outbound.sql_access_log import SqlAccessLog

    patient, med = setup
    family = make.family_of(patient)

    def broken(*_args, **_kwargs):
        raise RuntimeError("access_logs unavailable")

    monkeypatch.setattr(SqlAccessLog, "append_allowed", broken)
    r = TestClient(create_app(), raise_server_exceptions=False).get(
        f"/medications/{med['id']}", headers=auth(family)
    )
    assert r.status_code == 500
    assert "medication" not in r.text
