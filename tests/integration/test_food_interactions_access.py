"""Phân quyền GET /patients/{patient_id}/food-interactions (task 4.05: AC10–AC14b, AC17).

Bộ cross-patient của wf-health-endpoint: mỗi ca kiểm cả response lẫn access_logs.
"""

from uuid import uuid4

import pytest
from sqlalchemy import text

SCOPE = "canh_bao_tuong_tac"


def _log(actor, role, result, reason=None):
    return {
        "actor_user_id": actor,
        "actor_role": role,
        "data_scope": SCOPE,
        "result": result,
        "rejection_reason": reason,
    }


def _lookup(client, auth, caller, patient, **params):
    return client.get(f"/patients/{patient}/food-interactions", params=params, headers=auth(caller))


@pytest.fixture
def patient_with_med(client, make, auth, scheduled_body):
    """Người bệnh P có một thuốc đang dùng; trả (P, user_medication_id, tên thuốc)."""
    p = make.user()
    name = f"Thuốc kín {uuid4().hex[:8]}"
    r = client.post(
        "/medications",
        json=scheduled_body(make.catalog_medication(name=name)),
        headers=auth(p),
    )
    assert r.status_code == 201, r.text
    return p, r.json()["id"], name


@pytest.mark.parametrize("filtered", [False, True])
def test_self_allowed_logged__AC10(client, make, auth, patient_with_med, filtered):
    p, um, name = patient_with_med
    params = {"user_medication_id": um} if filtered else {}
    r = _lookup(client, auth, p, p, **params)
    assert r.status_code == 200, r.text
    assert name in r.text
    assert make.access_logs(p) == [_log(p, "patient", "allowed")]


def test_self_consent_revoked_403_denied__AC11(client, make, auth, patient_with_med):
    p, _, name = patient_with_med
    assert _lookup(client, auth, p, p).status_code == 200
    make.revoke_consent(p, "health_data")
    r = _lookup(client, auth, p, p)
    assert r.status_code == 403 and r.json() == {"detail": "consent_revoked"}
    assert name not in r.text
    assert make.access_logs(p) == [
        _log(p, "patient", "allowed"),
        _log(p, "patient", "denied", "consent_revoked"),
    ]


def test_stranger_403_denied_no_data__AC12(client, make, auth, patient_with_med):
    p, um, name = patient_with_med
    stranger = make.user()
    for params in ({}, {"user_medication_id": um}):
        r = _lookup(client, auth, stranger, p, **params)
        assert r.status_code == 403 and r.json() == {"detail": "khong_co_quyen"}
        assert name not in r.text and "medications" not in r.text
    assert make.access_logs(p) == [_log(stranger, "khong_co_quyen", "denied", "khong_co_quyen")] * 2


@pytest.mark.parametrize("filtered", [False, True])
def test_family_allowed__AC13(client, make, auth, patient_with_med, filtered):
    p, um, name = patient_with_med
    family = make.family_of(p)
    params = {"user_medication_id": um} if filtered else {}
    r = _lookup(client, auth, family, p, **params)
    assert r.status_code == 200, r.text
    assert name in r.text
    assert make.access_logs(p) == [_log(family, "family", "allowed")]


@pytest.mark.parametrize("revoke", ["sharing_off", "unlink", "family_sharing", "health_data"])
def test_family_denied_right_after_revoke__AC13(client, db, make, auth, patient_with_med, revoke):
    p, _, name = patient_with_med
    family = make.family_of(p)
    assert _lookup(client, auth, family, p).status_code == 200
    if revoke in ("family_sharing", "health_data"):
        make.revoke_consent(p, revoke)
    else:
        db.execute(
            text(
                "UPDATE caregiver_links SET "
                + (
                    "sharing_enabled = false"
                    if revoke == "sharing_off"
                    else "status = 'revoked', revoked_at = now()"
                )
                + " WHERE patient_user_id = :p AND family_user_id = :f"
            ),
            {"p": p, "f": family},
        )
    r = _lookup(client, auth, family, p)
    assert r.status_code == 403 and r.json() == {"detail": "khong_co_quyen"}
    assert name not in r.text
    assert [(x["actor_user_id"], x["result"]) for x in make.access_logs(p)] == [
        (family, "allowed"),
        (family, "denied"),
    ]


@pytest.mark.parametrize("missing", ["sharing_off", "family_sharing", "health_data"])
def test_family_missing_consent_or_sharing_denied(client, make, auth, missing):
    p = make.user(consents=() if missing == "health_data" else ("health_data",))
    if missing == "family_sharing":
        family = make.user()
        make.link(p, family)
    else:
        family = make.family_of(p, sharing=missing != "sharing_off")
    r = _lookup(client, auth, family, p)
    assert r.status_code == 403
    assert [(x["result"], x["rejection_reason"]) for x in make.access_logs(p)] == [
        ("denied", "khong_co_quyen")
    ]


def test_family_swaps_patient_id_denied(client, make, auth, patient_with_med):
    p, _, _ = patient_with_med
    other = make.user()
    family = make.family_of(p)
    r = _lookup(client, auth, family, other)
    assert r.status_code == 403
    assert make.access_logs(other) == [
        _log(family, "khong_co_quyen", "denied", "khong_co_quyen")
    ]
    assert make.access_logs(p) == []


def test_family_cannot_probe_other_patients_medication_id(
    client, make, auth, patient_with_med, scheduled_body
):
    """Người thân của P truyền user_medication_id của người khác → 404, không lộ dữ liệu."""
    p, _, _ = patient_with_med
    other = make.user()
    secret = f"Thuốc người khác {uuid4().hex[:8]}"
    r = client.post(
        "/medications",
        json=scheduled_body(make.catalog_medication(name=secret)),
        headers=auth(other),
    )
    assert r.status_code == 201, r.text
    family = make.family_of(p)
    r = _lookup(client, auth, family, p, user_medication_id=r.json()["id"])
    assert r.status_code == 404 and r.json() == {"detail": "user_medication_not_found"}
    assert secret not in r.text


def test_admin_403_denied__AC14(client, make, auth, patient_with_med):
    p, um, name = patient_with_med
    admin = make.user(admin=True)
    for params in ({}, {"user_medication_id": um}):
        r = _lookup(client, auth, admin, p, **params)
        assert r.status_code == 403 and r.json() == {"detail": "khong_co_quyen"}
        assert name not in r.text
    assert make.access_logs(p) == [_log(admin, "admin", "denied", "khong_co_quyen")] * 2


@pytest.mark.parametrize("admin", [False, True])
def test_unknown_patient_403_without_log(client, db, make, auth, admin):
    caller = make.user(admin=admin)
    r = _lookup(client, auth, caller, uuid4())
    assert r.status_code == 403 and r.json() == {"detail": "khong_co_quyen"}
    n = db.execute(
        text("SELECT count(*) FROM access_logs WHERE actor_user_id = :a"), {"a": caller}
    ).scalar_one()
    assert n == 0


def test_stranger_with_medication_id_gets_403_not_404__AC9(client, make, auth, patient_with_med):
    p, _, _ = patient_with_med
    stranger = make.user()
    r = _lookup(client, auth, stranger, p, user_medication_id=2_000_000_000)
    assert r.status_code == 403


def test_allowed_log_failure_fails_request__AC14b(make, auth, patient_with_med, monkeypatch):
    from fastapi.testclient import TestClient

    from drugtime.main import create_app
    from drugtime.modules.access.adapters.outbound.sql_access_log import SqlAccessLog

    p, _, name = patient_with_med

    def broken(*_args, **_kwargs):
        raise RuntimeError("access_logs unavailable")

    monkeypatch.setattr(SqlAccessLog, "append_allowed", broken)
    r = TestClient(create_app(), raise_server_exceptions=False).get(
        f"/patients/{p}/food-interactions", headers=auth(p)
    )
    assert r.status_code == 500
    assert name not in r.text and "medications" not in r.text
    assert make.access_logs(p) == []


def test_unauthenticated_401__AC17(client, patient_with_med):
    p, _, _ = patient_with_med
    path = f"/patients/{p}/food-interactions"
    assert client.get(path).status_code == 401
    assert client.get(path, headers={"Authorization": "Bearer x"}).status_code == 401


@pytest.mark.parametrize("who", ["patient", "family"])
def test_commit_failure_returns_no_data_and_no_log__AC24(make, auth, patient_with_med, who):
    """Commit transaction lỗi (không chỉ lỗi ghi dòng log) → không 2xx, không dữ liệu, không log."""
    from unittest.mock import patch

    from fastapi.testclient import TestClient
    from sqlalchemy.engine.base import RootTransaction

    from drugtime.main import create_app

    p, _, name = patient_with_med
    caller = p if who == "patient" else make.family_of(p)
    client = TestClient(create_app(), raise_server_exceptions=False)

    def failing_commit(self):
        raise RuntimeError("simulated commit failure")

    with patch.object(RootTransaction, "commit", failing_commit):
        r = client.get(f"/patients/{p}/food-interactions", headers=auth(caller))
    assert r.status_code == 500
    assert name not in r.text and "disclaimer" not in r.text
    assert make.access_logs(p) == []
