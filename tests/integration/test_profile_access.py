from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, text

from drugtime.main import create_app
from drugtime.modules.medication.adapters.inbound import profile_http
from drugtime.shared.db import get_engine

OPS = [
    ("get", "/profile", None),
    ("put", "/profile", {"full_name": "Changed", "date_of_birth": "2000-01-01", "gender": "nam"}),
    ("post", "/profile/conditions", {"condition_id": 1}),
    ("patch", "/profile/conditions/{id}", {"stage": "Changed"}),
    ("delete", "/profile/conditions/{id}", None),
]


def setup_link(db, make):
    user = make.user()
    cid = db.execute(
        text(
            "INSERT INTO conditions (name,medical_nature,data_role) "
            "VALUES (:n,'benh_ly','dieu_chinh_thuoc_khac') RETURNING id"
        ),
        {"n": str(uuid4())},
    ).scalar_one()
    link = db.execute(
        text(
            "INSERT INTO user_conditions (user_id,condition_id,subtype,stage) "
            "VALUES (:u,:c,'Private subtype','Private stage') RETURNING id"
        ),
        {"u": user, "c": cid},
    ).scalar_one()
    return user, cid, link


def snapshot(db, user):
    profile = db.execute(
        text("SELECT full_name,date_of_birth,gender FROM users WHERE id=:u"), {"u": user}
    ).one()
    links = db.execute(
        text(
            "SELECT id,condition_id,subtype,stage FROM user_conditions WHERE user_id=:u ORDER BY id"
        ),
        {"u": user},
    ).all()
    logs = db.execute(
        text("SELECT id FROM access_logs WHERE patient_user_id=:u ORDER BY id"), {"u": user}
    ).all()
    return profile, links, logs


@pytest.mark.parametrize("method,path,body", OPS)
def test_revoked_consent_next_request_denied_and_audited__AC13_AC14(
    client, db, make, auth, method, path, body
):
    user, cid, link = setup_link(db, make)
    headers = auth(user)
    assert client.get("/profile", headers=headers).status_code == 200
    make.revoke_consent(user, "health_data")
    before = snapshot(db, user)
    payload = {**body, "condition_id": cid} if method == "post" else body
    response = client.request(method, path.format(id=link), json=payload, headers=headers)
    assert response.status_code == 403 and response.json() == {"detail": "consent_revoked"}
    after = snapshot(db, user)
    assert before[:2] == after[:2]
    logs = make.access_logs(user)
    assert logs[-1] == {
        "actor_user_id": user,
        "actor_role": "patient",
        "data_scope": "ho_so_suc_khoe",
        "result": "denied",
        "rejection_reason": "consent_revoked",
    }
    assert len(after[2]) == len(before[2]) + 1
    assert client.get("/conditions", headers=headers).status_code == 200


@pytest.mark.parametrize("method", ["patch", "delete"])
def test_other_users_link_missing_same_404__AC11(client, db, make, auth, method):
    owner, _, link = setup_link(db, make)
    stranger = make.user()
    before = snapshot(db, owner)
    payload = {"stage": None} if method == "patch" else None
    responses = [
        client.request(
            method, f"/profile/conditions/{identifier}", json=payload, headers=auth(stranger)
        )
        for identifier in (link, 9223372036854775807)
    ]
    assert all(r.status_code == 404 for r in responses)
    assert responses[0].json() == responses[1].json() == {"detail": "user_condition_not_found"}
    assert snapshot(db, owner) == before
    assert client.get("/profile", headers=auth(stranger)).json()["conditions"] == []


@pytest.mark.parametrize("method,path,body", OPS + [("get", "/conditions", None)])
@pytest.mark.parametrize("kind", ["missing", "invalid", "expired", "erased"])
def test_missing_invalid_expired_erased_auth__AC12(
    client, db, make, auth, method, path, body, kind
):
    from drugtime.modules.identity.application.sign_in import issue_app_session
    from drugtime.modules.identity.domain.user import SessionType

    user = make.user()
    headers = {}
    if kind == "invalid":
        headers = {"Authorization": "Bearer invalid-token"}
    elif kind == "expired":
        token = issue_app_session(
            user, SessionType.MOBILE, datetime.now(UTC) - timedelta(days=100)
        ).token
        headers = {"Authorization": f"Bearer {token}"}
    elif kind == "erased":
        headers = auth(user)
        db.execute(
            text(
                "UPDATE users SET erased_at=now(),full_name=NULL,date_of_birth=NULL,"
                "gender=NULL,email=NULL,phone_number=NULL WHERE id=:u"
            ),
            {"u": user},
        )
    before = snapshot(db, user)
    response = client.request(method, path.format(id=1), json=body, headers=headers)
    assert response.status_code == 401
    assert snapshot(db, user) == before


@pytest.mark.parametrize("method,path,body", OPS)
@pytest.mark.parametrize("failure", ["audit", "commit"])
def test_audit_and_commit_failures_no_ack_and_rollback__AC15(
    db, make, auth, monkeypatch, method, path, body, failure
):
    user, cid, link = setup_link(db, make)
    before = snapshot(db, user)
    real = profile_http.unit_of_work

    @contextmanager
    def fail_commit():
        with real() as uow:
            yield uow
            raise RuntimeError("injected commit failure")

    def fail_audit(conn, cursor, statement, parameters, context, executemany):
        if "INSERT INTO access_logs" in statement:
            raise RuntimeError("injected audit transport failure")

    if failure == "commit":
        monkeypatch.setattr(profile_http, "unit_of_work", fail_commit)
    else:
        event.listen(get_engine(), "before_cursor_execute", fail_audit)
    try:
        with TestClient(create_app(), raise_server_exceptions=False) as client:
            payload = {**body, "condition_id": cid} if method == "post" else body
            if method == "post":
                db.execute(text("DELETE FROM user_conditions WHERE id=:i"), {"i": link})
                before = snapshot(db, user)
            response = client.request(
                method, path.format(id=link), json=payload, headers=auth(user)
            )
        assert response.status_code == 500
        assert response.json() == {"detail": "Internal server error"}
        assert snapshot(db, user) == before
    finally:
        if failure == "audit":
            event.remove(get_engine(), "before_cursor_execute", fail_audit)


def test_denied_audit_failure_fails_closed__AC15(db, make, auth):
    user = make.user(consents=())
    before = snapshot(db, user)

    def fail(conn, cursor, statement, parameters, context, executemany):
        if "INSERT INTO access_logs" in statement:
            raise RuntimeError("audit unavailable")

    event.listen(get_engine(), "before_cursor_execute", fail)
    try:
        response = TestClient(create_app(), raise_server_exceptions=False).get(
            "/profile", headers=auth(user)
        )
        assert response.status_code == 500
        assert response.json() == {"detail": "Internal server error"}
        assert snapshot(db, user) == before
    finally:
        event.remove(get_engine(), "before_cursor_execute", fail)
