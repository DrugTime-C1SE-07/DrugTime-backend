from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from unittest.mock import Mock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, text

from drugtime.main import create_app
from drugtime.modules.medication.adapters.inbound import profile_http
from drugtime.shared.db import get_engine

BASE = {"full_name": "Bao", "date_of_birth": "2000-01-01", "gender": "nam"}


def fresh_phone():
    return "+84" + str(100000000 + uuid4().int % 900000000)


def snapshot(db, user):
    return db.execute(
        text("SELECT full_name,date_of_birth,gender,email,phone_number FROM users WHERE id=:u"),
        {"u": user},
    ).one()


@pytest.fixture
def no_auth_phone_changes(monkeypatch):
    from drugtime.modules.identity.adapters.outbound.supabase_auth import SupabaseAuth

    calls = []
    for name in ("update_email", "request_otp", "verify_otp"):
        call = Mock(side_effect=AssertionError("Contact phone must not call Supabase Auth"))
        monkeypatch.setattr(SupabaseAuth, name, call)
        calls.append(call)
    yield
    for call in calls:
        call.assert_not_called()


def test_contact_phone_initially_null__AC19(client, make, auth):
    user = make.user()
    response = client.get("/profile", headers=auth(user))
    assert response.status_code == 200
    assert response.json()["phone_number"] is None
    assert response.headers["cache-control"] == "no-store"
    assert make.access_logs(user)[-1]["result"] == "allowed"


@pytest.mark.parametrize("form", ["local", "international", "spaces_hyphens"])
def test_contact_phone_round_trip__AC19_AC20_AC21(
    client, db, make, auth, form, no_auth_phone_changes
):
    user = make.user()
    before = snapshot(db, user)
    phone = fresh_phone()
    raw = {
        "local": "0" + phone[3:],
        "international": phone,
        "spaces_hyphens": " 0" + phone[3:6] + " " + phone[6:9] + "-" + phone[9:] + " ",
    }[form]
    headers = auth(user)
    result = client.put("/profile", json={**BASE, "phone_number": raw}, headers=headers)
    assert result.status_code == 204 and result.content == b"", result.text
    after = snapshot(db, user)
    assert after.phone_number == phone and after.email == before.email
    response = client.get("/profile", headers=headers)
    assert response.status_code == 200
    assert response.json()["phone_number"] == phone
    assert response.json()["email"] == before.email
    assert response.json()["conditions"] == []
    assert response.headers["cache-control"] == "no-store"


def test_contact_phone_omission_preserves__AC22(client, db, make, auth, no_auth_phone_changes):
    user, phone = make.user(), fresh_phone()
    headers = auth(user)
    assert (
        client.put("/profile", json={**BASE, "phone_number": phone}, headers=headers).status_code
        == 204
    )
    assert client.put("/profile", json=BASE, headers=headers).status_code == 204
    assert snapshot(db, user).phone_number == phone
    assert client.get("/profile", headers=headers).json()["phone_number"] == phone


@pytest.mark.parametrize("raw_length", [1, 64, 65])
def test_contact_phone_raw_length_boundaries__AC22(client, db, make, auth, raw_length):
    user, phone = make.user(), fresh_phone()
    raw = "1" if raw_length == 1 else phone.ljust(raw_length)
    before = snapshot(db, user)
    response = client.put("/profile", headers=auth(user), json={**BASE, "phone_number": raw})
    if raw_length == 64:
        assert response.status_code == 204
        assert snapshot(db, user).phone_number == phone
    else:
        assert response.status_code == 422
        assert snapshot(db, user) == before


def test_contact_phone_repeat_value__AC20(client, db, make, auth, no_auth_phone_changes):
    user, phone = make.user(), fresh_phone()
    headers = auth(user)
    for _ in range(2):
        response = client.put("/profile", headers=headers, json={**BASE, "phone_number": phone})
        assert response.status_code == 204
    assert snapshot(db, user).phone_number == phone
    assert [log["result"] for log in make.access_logs(user)] == ["allowed", "allowed"]


@pytest.mark.parametrize(
    "value",
    [
        None,
        "",
        " ",
        912345678,
        True,
        "bad",
        "+012345678",
        "+1234567",
        "+1234567890123456",
        "+84١٢٣٤٥٦٧٨٩",
        "+84912345678\x00",
        "1" * 64,
        "1" * 65,
    ],
)
def test_contact_phone_invalid_atomic__AC21_AC22(
    client, db, make, auth, value, no_auth_phone_changes
):
    user = make.user()
    before = snapshot(db, user)
    # Include a new email to prove phone validation precedes Auth side effects.
    response = client.put(
        "/profile",
        headers=auth(user),
        json={
            **BASE,
            "full_name": "Must roll back",
            "email": "new@example.com",
            "phone_number": value,
        },
    )
    assert response.status_code == 422, response.text
    assert snapshot(db, user) == before
    if isinstance(value, str) and 0 < len(value) <= 64:
        assert response.json() == {"detail": "invalid_phone"}


@pytest.mark.parametrize("digits", [8, 15])
def test_contact_phone_e164_valid_boundaries__AC20(client, db, make, auth, digits):
    user = make.user()
    phone = "+" + "1" + str(uuid4().int % (10 ** (digits - 1))).zfill(digits - 1)
    response = client.put("/profile", headers=auth(user), json={**BASE, "phone_number": phone})
    assert response.status_code == 204, response.text
    assert snapshot(db, user).phone_number == phone


def test_contact_phone_duplicate_rollback__AC23(client, db, make, auth, no_auth_phone_changes):
    owner, other, phone = make.user(), make.user(), fresh_phone()
    db.execute(text("UPDATE users SET phone_number=:p WHERE id=:u"), {"p": phone, "u": owner})
    before = snapshot(db, other)
    response = client.put("/profile", headers=auth(other), json={**BASE, "phone_number": phone})
    assert response.status_code == 409
    assert response.json() == {"detail": "phone_change_unavailable"}
    assert snapshot(db, other) == before
    assert snapshot(db, owner).phone_number == phone


def test_contact_phone_concurrent_duplicate__AC23(
    db, admin_engine, make, auth, wait_for_lock_waiters
):
    users, phone = [make.user(), make.user()], fresh_phone()
    before = {user: snapshot(db, user) for user in users}

    def request(user):
        with TestClient(create_app()) as local:
            return local.put("/profile", headers=auth(user), json={**BASE, "phone_number": phone})

    with admin_engine.execution_options(isolation_level="READ COMMITTED").connect() as blocker:
        tx = blocker.begin()
        blocker.execute(text("LOCK TABLE users IN SHARE MODE"))
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(request, user) for user in users]
            try:
                wait_for_lock_waiters(2)
            finally:
                tx.rollback()
            responses = [future.result(timeout=30) for future in futures]
    assert sorted(r.status_code for r in responses) == [204, 409]
    for user, response in zip(users, responses, strict=True):
        if response.status_code == 409:
            assert response.json() == {"detail": "phone_change_unavailable"}
            assert snapshot(db, user) == before[user]
    assert (
        db.execute(
            text("SELECT count(*) FROM users WHERE phone_number=:p"), {"p": phone}
        ).scalar_one()
        == 1
    )


@pytest.mark.parametrize("method", ["get", "put"])
def test_contact_phone_revoked_immediately__AC24(client, db, make, auth, method):
    user = make.user()
    assert client.get("/profile", headers=auth(user)).status_code == 200
    make.revoke_consent(user, "health_data")
    before = snapshot(db, user)
    payload = {**BASE, "phone_number": fresh_phone()} if method == "put" else None
    response = client.request(method, "/profile", headers=auth(user), json=payload)
    assert response.status_code == 403
    assert response.json() == {"detail": "consent_revoked"}
    assert snapshot(db, user) == before
    assert make.access_logs(user)[-1]["result"] == "denied"


@pytest.mark.parametrize("linked", [False, True])
def test_contact_phone_self_only__AC24(client, db, make, auth, linked):
    patient = make.user()
    caller = make.family_of(patient) if linked else make.user()
    patient_phone, caller_phone = fresh_phone(), fresh_phone()
    for user, phone in ((patient, patient_phone), (caller, caller_phone)):
        db.execute(text("UPDATE users SET phone_number=:p WHERE id=:u"), {"p": phone, "u": user})
    own = client.get("/profile", headers=auth(caller))
    assert own.status_code == 200
    assert own.json()["phone_number"] == caller_phone
    for selector in ("patient_id", "user_id"):
        response = client.get(f"/profile?{selector}={patient}", headers=auth(caller))
        assert response.status_code == 422
        assert response.json() == {"detail": "profile_is_self_only"}
        assert patient_phone not in response.text
        denied_write = client.put(
            f"/profile?{selector}={patient}",
            headers=auth(caller),
            json={**BASE, "phone_number": fresh_phone()},
        )
        assert denied_write.status_code == 422
        assert denied_write.json() == {"detail": "profile_is_self_only"}
    assert snapshot(db, patient).phone_number == patient_phone
    assert snapshot(db, caller).phone_number == caller_phone
    assert make.access_logs(patient) == []
    assert make.access_logs(caller)[-1]["result"] == "allowed"


@pytest.mark.parametrize("method", ["get", "put"])
def test_contact_phone_admin_denied__AC24(client, db, admin_auth, make, method):
    user, headers = admin_auth
    before = snapshot(db, user)
    payload = {**BASE, "phone_number": fresh_phone()} if method == "put" else None
    response = client.request(method, "/profile", headers=headers, json=payload)
    assert response.status_code == 403
    assert snapshot(db, user) == before
    assert make.access_logs(user)[-1]["result"] == "denied"


@pytest.mark.parametrize("headers", [{}, {"Authorization": "Bearer bad-token"}])
@pytest.mark.parametrize("method", ["get", "put"])
def test_contact_phone_auth_required__AC24(client, headers, method):
    payload = {**BASE, "phone_number": fresh_phone()} if method == "put" else None
    response = client.request(method, "/profile", headers=headers, json=payload)
    assert response.status_code == 401
    assert "phone_number" not in response.text


@pytest.mark.parametrize("method", ["get", "put"])
@pytest.mark.parametrize("failure", ["audit", "commit"])
def test_contact_phone_failure_no_data_or_ack__AC25(db, make, auth, monkeypatch, method, failure):
    user, phone = make.user(), fresh_phone()
    db.execute(text("UPDATE users SET phone_number=:p WHERE id=:u"), {"p": phone, "u": user})
    before = snapshot(db, user)
    real = profile_http.unit_of_work

    @contextmanager
    def fail_commit():
        with real() as uow:
            yield uow
            raise RuntimeError("injected commit failure")

    def fail_audit(conn, cursor, statement, parameters, context, executemany):
        if "INSERT INTO access_logs" in statement:
            raise RuntimeError("injected audit failure")

    if failure == "commit":
        monkeypatch.setattr(profile_http, "unit_of_work", fail_commit)
    else:
        event.listen(get_engine(), "before_cursor_execute", fail_audit)
    try:
        with TestClient(create_app(), raise_server_exceptions=False) as local:
            payload = {**BASE, "phone_number": fresh_phone()} if method == "put" else None
            response = local.request(method, "/profile", headers=auth(user), json=payload)
        assert response.status_code == 500
        assert response.json() == {"detail": "Internal server error"}
        assert phone not in response.text
        assert snapshot(db, user) == before
    finally:
        if failure == "audit":
            event.remove(get_engine(), "before_cursor_execute", fail_audit)


def test_contact_phone_audit_no_payload__AC25(client, db, make, auth):
    user, phone = make.user(), fresh_phone()
    email = snapshot(db, user).email
    headers = auth(user)
    assert (
        client.put("/profile", headers=headers, json={**BASE, "phone_number": phone}).status_code
        == 204
    )
    assert client.get("/profile", headers=headers).status_code == 200
    rows = (
        db.execute(
            text("SELECT to_jsonb(a)::text FROM access_logs a WHERE patient_user_id=:u"),
            {"u": user},
        )
        .scalars()
        .all()
    )
    assert len(rows) == 2
    assert all(phone not in row and email not in row and "Bao" not in row for row in rows)
    assert [row["result"] for row in make.access_logs(user)] == ["allowed", "allowed"]
