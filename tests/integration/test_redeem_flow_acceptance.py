"""Acceptance gaps for task 3.15; existing redeem and PEP suites cover the rest."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import text

from drugtime.modules.family.domain.link_code import generate_code
from drugtime.modules.family.domain.link_request import next_vn_midnight


def _redeem(client, auth, family, code):
    return client.post(
        "/family/link-requests",
        json={"code": code, "client_uuid": str(uuid4())},
        headers=auth(family),
    )


def test_owner_regrant_via_api_reuses_code_and_redeems__AC7(client, db, make, auth):
    patient = make.user(consents=())
    family = make.user(consents=())
    consent = {"purpose": "family_sharing", "document_version": "2026-10-v1"}
    assert client.post("/consents", json=consent, headers=auth(patient)).status_code == 201
    code_response = client.get("/family/link-code", headers=auth(patient))
    assert code_response.status_code == 200
    code = code_response.json()["code"]

    assert client.post(
        "/consents/family_sharing/withdraw", headers=auth(patient)
    ).status_code == 200
    hidden = _redeem(client, auth, family, code)
    unknown_code = generate_code()
    while unknown_code == code:
        unknown_code = generate_code()
    unknown = _redeem(client, auth, family, unknown_code)
    assert (hidden.status_code, hidden.json()) == (unknown.status_code, unknown.json()) == (
        404,
        {"detail": "link_code_not_found"},
    )
    assert db.execute(
        text("SELECT count(*) FROM caregiver_links WHERE family_user_id = :f"), {"f": family}
    ).scalar_one() == 0

    assert client.post("/consents", json=consent, headers=auth(patient)).status_code == 201
    assert client.get("/family/link-code", headers=auth(patient)).json()["code"] == code
    accepted = _redeem(client, auth, family, code)
    assert accepted.status_code == 201
    assert accepted.json()["status"] == "pending"
    assert db.execute(
        text(
            "SELECT count(*) FROM caregiver_links WHERE patient_user_id = :p "
            "AND family_user_id = :f AND status = 'pending' AND sharing_enabled = false"
        ),
        {"p": patient, "f": family},
    ).scalar_one() == 1


def test_daily_quota_last_second_and_midnight_vn__AC8(
    client, db, make, auth, monkeypatch
):
    from drugtime.shared import clock

    # A fixed UTC instant makes the boundary independent of the test machine's clock.
    midnight = next_vn_midnight(datetime(2026, 10, 23, 12, tzinfo=UTC))
    family = make.user()
    for i in range(10):
        patient = make.user(consents=("health_data", "family_sharing"))
        db.execute(
            text(
                "INSERT INTO caregiver_links "
                "(patient_user_id, family_user_id, status, linked_at) "
                "VALUES (:p, :f, 'pending', :at)"
            ),
            {"p": patient, "f": family, "at": midnight - timedelta(hours=1, minutes=i)},
        )
    patient = make.user(consents=("health_data", "family_sharing"))
    code_response = client.get("/family/link-code", headers=auth(patient))
    assert code_response.status_code == 200
    code = code_response.json()["code"]
    monkeypatch.setattr(clock, "now", lambda: midnight - timedelta(seconds=1))
    blocked = _redeem(client, auth, family, code)
    assert blocked.status_code == 429
    assert blocked.json() == {"detail": "link_request_daily_limit"}
    assert blocked.headers["Retry-After"] == "1"
    assert db.execute(
        text(
            "SELECT count(*) FROM caregiver_links "
            "WHERE patient_user_id = :p AND family_user_id = :f"
        ),
        {"p": patient, "f": family},
    ).scalar_one() == 0

    monkeypatch.setattr(clock, "now", lambda: midnight)
    accepted = _redeem(client, auth, family, code)
    assert accepted.status_code == 201
    assert accepted.json()["status"] == "pending"
