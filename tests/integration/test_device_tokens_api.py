"""Task 3.21 token ownership, atomic refresh and synchronized DB contention."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from drugtime.main import create_app
from drugtime.modules.identity import api as identity
from drugtime.modules.identity.adapters.outbound.sql_device_tokens import SqlDeviceTokens
from drugtime.modules.identity.application.sign_in import issue_app_session
from drugtime.modules.identity.domain.user import SessionType
from drugtime.shared.db import SqlUnitOfWork, unit_of_work


def put(client, headers, token, previous=None, **extra):
    body = {"fcm_token": token, "platform": "android", **extra}
    if previous is not None:
        body["previous_fcm_token"] = previous
    return client.put("/me/device-tokens", headers=headers, json=body)


def delete(client, headers, token):
    return client.request("DELETE", "/me/device-tokens", headers=headers, json={"fcm_token": token})


def test_replay_refresh_logout_and_dispatch_selection__AC1_AC8(client, make, auth, db):
    owner, other = make.user(), make.user()
    h = auth(owner)
    old, new = uuid4().hex, uuid4().hex
    for _ in range(2):
        response = put(client, h, old)
        assert response.status_code == 204 and response.content == b""
    assert (
        db.execute(
            text("SELECT count(*) FROM device_tokens WHERE user_id=:u"), {"u": owner}
        ).scalar_one()
        == 1
    )
    response = put(client, auth(other), old)
    assert response.status_code == 409 and response.json() == {"detail": "device_token_in_use"}
    assert put(client, h, new, previous=old).status_code == 204
    with unit_of_work() as uow:
        assert identity.android_tokens(uow, [owner]) == [(owner, new)]
    assert delete(client, auth(other), new).status_code == 204
    for _ in range(2):
        response = delete(client, h, new)
        assert response.status_code == 204 and response.content == b""
    with unit_of_work() as uow:
        assert identity.android_tokens(uow, [owner]) == []


def test_conflicting_refresh_rolls_back_and_foreign_previous_is_preserved__AC1(
    client, make, auth, db
):
    a, b = make.user(), make.user()
    old, occupied, fresh = [uuid4().hex for _ in range(3)]
    assert put(client, auth(a), old).status_code == 204
    assert put(client, auth(b), occupied).status_code == 204
    assert put(client, auth(a), occupied, previous=old).status_code == 409
    assert put(client, auth(a), fresh, previous=occupied).status_code == 204
    rows = dict(
        db.execute(
            text("SELECT fcm_token,user_id FROM device_tokens WHERE fcm_token=ANY(:ts)"),
            {"ts": [old, occupied, fresh]},
        ).all()
    )
    assert rows == {old: a, fresh: a, occupied: b}


@pytest.mark.parametrize(
    "body",
    [
        {"fcm_token": "", "platform": "android"},
        {"fcm_token": "a b", "platform": "android"},
        {"fcm_token": "a", "platform": "ios"},
        {"fcm_token": "a", "platform": "android", "previous_fcm_token": " "},
        {"fcm_token": "a", "platform": "android", "user_id": "injected"},
    ],
)
def test_invalid_registration_is_rejected__AC1(client, make, auth, body):
    response = client.put("/me/device-tokens", headers=auth(make.user()), json=body)
    assert response.status_code == 422


def test_one_character_token_boundary__AC1(client, make, auth):
    headers = auth(make.user())
    # Token syntax has minLength=1 and no declared maximum. Remove the synthetic
    # boundary token after registration so repeated runs remain independent.
    token = "~"
    response = put(client, headers, token)
    assert response.status_code == 204
    assert delete(client, headers, token).status_code == 204


@pytest.mark.parametrize("method", ["PUT", "DELETE"])
def test_missing_expired_and_admin_sessions_rejected__AC1_AC8(
    client, make, auth, admin_auth, method
):
    owner = make.user()
    expired = issue_app_session(
        owner, SessionType.MOBILE, datetime.now(UTC) - timedelta(days=365)
    ).token
    _, admin_headers = admin_auth
    body = {"fcm_token": uuid4().hex}
    if method == "PUT":
        body["platform"] = "android"
    for headers, expected in [
        ({}, 401),
        ({"Authorization": f"Bearer {expired}"}, 401),
        (admin_headers, 403),
    ]:
        response = client.request(method, "/me/device-tokens", headers=headers, json=body)
        assert response.status_code == expected


@pytest.mark.parametrize("same_owner", [False, True])
def test_concurrent_registration_serializes_absent_token__AC1(
    admin_engine, db, make, auth, wait_for_lock_waiters, same_owner
):
    a = make.user()
    b = a if same_owner else make.user()
    token = uuid4().hex
    headers = auth(b)
    with admin_engine.execution_options(isolation_level="READ COMMITTED").connect() as blocker:
        tx = blocker.begin()
        SqlDeviceTokens().register(SqlUnitOfWork(blocker), a, token, None)
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(lambda: put(TestClient(create_app()), headers, token))
            try:
                wait_for_lock_waiters(1)
            finally:
                tx.commit()
            response = pending.result(timeout=15)
    assert response.status_code == (204 if same_owner else 409)
    assert db.execute(
        text("SELECT user_id FROM device_tokens WHERE fcm_token=:t"), {"t": token}
    ).all() == [(a,)]


def test_concurrent_refresh_then_cleanup_has_no_token_left__AC1_AC8(
    admin_engine, db, make, auth, wait_for_lock_waiters
):
    owner = make.user()
    headers = auth(owner)
    old, fresh = uuid4().hex, uuid4().hex
    with admin_engine.execution_options(isolation_level="READ COMMITTED").connect() as blocker:
        tx = blocker.begin()
        repository = SqlDeviceTokens()
        repository.register(SqlUnitOfWork(blocker), owner, old, None)
        repository.register(SqlUnitOfWork(blocker), owner, fresh, old)
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(lambda: delete(TestClient(create_app()), headers, fresh))
            try:
                wait_for_lock_waiters(1)
            finally:
                tx.commit()
            assert pending.result(timeout=15).status_code == 204
    assert (
        db.execute(
            text("SELECT count(*) FROM device_tokens WHERE user_id=:u"), {"u": owner}
        ).scalar_one()
        == 0
    )
