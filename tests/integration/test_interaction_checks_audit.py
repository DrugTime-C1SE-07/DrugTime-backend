"""Audit của POST /patients/{patient_id}/interaction-checks sau khi sửa ở task 4.05 (AC21, G15).

Hành vi cho/từ chối của endpoint 4.02 không đổi; chỉ thêm dòng access_logs khi người bệnh tự gọi.
"""

import pytest

SCOPE = "canh_bao_tuong_tac"


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
