from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from threading import Barrier, Event
from types import SimpleNamespace

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DataError

from drugtime.modules.consent.adapters.inbound import deletion_http
from drugtime.modules.identity.adapters.inbound import email_change_http
from drugtime.modules.identity.adapters.outbound.sql_email_change import SqlEmailChange
from drugtime.shared.errors import ServiceUnavailable

EMAIL = "/me/email-change"
DELETION = "/data-deletion-requests"


@dataclass
class AuthProvider:
    email: str
    failure: str = ""
    entered: Event | None = None
    release: Event | None = None
    updates: int = 0

    def verified_email(self, _uid):
        return self.email

    def update_email(self, _uid, email):
        self.updates += 1
        if self.entered is not None:
            self.entered.set()
            assert self.release.wait(timeout=10)
        if self.failure == "before_auth":
            raise ServiceUnavailable("service_unavailable")
        self.email = email
        if self.failure == "after_auth":
            raise ServiceUnavailable("service_unavailable")


@pytest.fixture
def flow(client, make, auth, monkeypatch):
    uid = make.user()
    old = f"{uid}@test.local"
    new = f"new-{uid}@example.test"
    provider = AuthProvider(old)
    clock = SimpleNamespace(at=datetime(2026, 11, 11, 3, tzinfo=UTC))
    outbox = []
    settings = SimpleNamespace(
        email_change_otp_hmac_key="email-" * 8,
        deletion_otp_hmac_key="delete-" * 8,
    )
    monkeypatch.setattr(email_change_http, "SupabaseAuth", lambda: provider)
    monkeypatch.setattr(deletion_http.identity, "verified_email", provider.verified_email)
    for module in (email_change_http, deletion_http):
        monkeypatch.setattr(module, "now", lambda: clock.at)
        monkeypatch.setattr(module, "get_settings", lambda: settings)
    monkeypatch.setattr(
        email_change_http, "send_email_change_otp", lambda *args: outbox.append(args)
    )
    monkeypatch.setattr(deletion_http, "send_deletion_otp", lambda *args: outbox.append(args))
    headers = auth(uid)
    return SimpleNamespace(
        uid=uid, old=old, new=new, provider=provider, clock=clock, outbox=outbox,
        post=lambda path, **kwargs: client.post(path, headers=headers, **kwargs),
    )


def issued_proof(flow, response, recipient, status):
    assert response.status_code == status, response.text
    assert response.headers["cache-control"] == "no-store"
    assert datetime.fromisoformat(response.json()["expires_at"]) == flow.clock.at + timedelta(
        minutes=5
    )
    assert flow.outbox[-1][0] == recipient
    return {"challenge_id": response.json()["challenge_id"], "otp": flow.outbox[-1][1]}


def start(flow):
    response = flow.post(EMAIL + "/otp", json={"new_email": flow.new})
    return issued_proof(flow, response, flow.old, 201)


def verify(flow, proof):
    response = flow.post(EMAIL + "/verify-current", json=proof)
    return issued_proof(flow, response, flow.new, 200)


def deletion_proof(flow, recipient):
    return issued_proof(flow, flow.post(DELETION + "/otp"), recipient, 201)


def profile_email(db, flow):
    return db.execute(
        text("SELECT email FROM users WHERE id=:uid"), {"uid": flow.uid}
    ).scalar_one()


def change_stage(db, flow):
    return db.execute(
        text("SELECT stage FROM email_change_challenges WHERE user_id=:uid"),
        {"uid": flow.uid},
    ).scalar_one()


def test_change_email_with_both_proofs_and_invalidate_deletion_otp__AC2(flow, db):
    stale = deletion_proof(flow, flow.old)
    first = start(flow)
    assert flow.post(EMAIL + "/confirm", json=first).status_code == 422
    assert profile_email(db, flow) == flow.old
    assert flow.provider.updates == 0
    assert len(flow.outbox) == 2

    second = verify(flow, first)
    assert second["challenge_id"] == first["challenge_id"]
    assert flow.post(EMAIL + "/verify-current", json=first).status_code == 422
    assert len(flow.outbox) == 3
    assert profile_email(db, flow) == flow.old

    barrier = Barrier(2, timeout=5)

    def confirm():
        barrier.wait()
        return flow.post(EMAIL + "/confirm", json=second).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        attempts = [pool.submit(confirm), pool.submit(confirm)]
        assert sorted(attempt.result(timeout=10) for attempt in attempts) == [204, 422]
    assert flow.provider.updates == 1
    assert flow.provider.email == profile_email(db, flow) == flow.new
    assert flow.post(DELETION, json=stale).status_code == 422
    flow.clock.at += timedelta(minutes=1)
    assert flow.post(DELETION, json=deletion_proof(flow, flow.new)).status_code == 201


def test_email_resend_cooldown_and_replaced_expired_otp__AC2(flow, db):
    old_proof = start(flow)
    response = flow.post(EMAIL + "/otp", json={"new_email": flow.new})
    assert response.status_code == 429
    assert response.json() == {"detail": "email_change_rate_limited"}
    flow.clock.at += timedelta(minutes=1)
    fresh_proof = start(flow)
    assert old_proof["challenge_id"] != fresh_proof["challenge_id"]
    assert flow.post(EMAIL + "/verify-current", json=old_proof).status_code == 422
    wrong_digit = str((int(fresh_proof["otp"][0]) + 1) % 10)
    wrong = {**fresh_proof, "otp": wrong_digit + fresh_proof["otp"][1:]}
    assert flow.post(EMAIL + "/verify-current", json=wrong).status_code == 422
    flow.clock.at += timedelta(minutes=5)
    assert flow.post(EMAIL + "/verify-current", json=fresh_proof).status_code == 422
    assert [message[0] for message in flow.outbox] == [flow.old, flow.old]
    assert profile_email(db, flow) == flow.old


@pytest.mark.parametrize("fault", ["before_auth", "after_auth", "db_rollback"])
def test_email_change_recovery_blocks_deletion_until_addresses_agree__AC2(
    flow, db, monkeypatch, fault
):
    stale = deletion_proof(flow, flow.old)
    second = verify(flow, start(flow))
    flow.provider.failure = fault
    finish = SqlEmailChange.finish

    def fail_finalize(store, conn, uid, state):
        finish(store, conn, uid, state)
        conn.execute(text("SELECT 1 / 0"))

    if fault == "db_rollback":
        monkeypatch.setattr(SqlEmailChange, "finish", fail_finalize)
    assert flow.post(EMAIL + "/confirm", json=second).status_code == 503
    assert change_stage(db, flow) == "applying"
    assert profile_email(db, flow) == flow.old
    assert flow.provider.email == (flow.old if fault == "before_auth" else flow.new)
    before = list(flow.outbox)
    assert flow.post(DELETION + "/otp").status_code == 503
    assert flow.post(DELETION, json=stale).status_code == 503
    assert flow.outbox == before

    if fault != "before_auth":
        monkeypatch.setattr(SqlEmailChange, "finish", fail_finalize)
        with pytest.raises(DataError, match="division by zero"):
            email_change_http.get_email_change().reconcile(flow.uid)
        assert change_stage(db, flow) == "applying"
        assert profile_email(db, flow) == flow.old
        assert flow.post(DELETION + "/otp").status_code == 503
        assert flow.outbox == before
    monkeypatch.setattr(SqlEmailChange, "finish", finish)
    email_change_http.get_email_change().reconcile(flow.uid)
    assert change_stage(db, flow) == "done"
    assert profile_email(db, flow) == flow.provider.email
    assert flow.post(DELETION, json=stale).status_code == (
        201 if fault == "before_auth" else 422
    )


def test_email_change_holds_deletion_confirmation_until_old_otp_invalidated__AC2(
    flow, db, wait_for_lock_waiters
):
    stale = deletion_proof(flow, flow.old)
    second = verify(flow, start(flow))
    flow.provider.entered = Event()
    flow.provider.release = Event()
    with ThreadPoolExecutor(max_workers=2) as pool:
        change = pool.submit(flow.post, EMAIL + "/confirm", json=second)
        try:
            assert flow.provider.entered.wait(timeout=5)
            deletion = pool.submit(flow.post, DELETION, json=stale)
            wait_for_lock_waiters(1, deadline_s=4)
            assert not deletion.done()
        finally:
            flow.provider.release.set()
        assert change.result(timeout=5).status_code == 204
        assert deletion.result(timeout=5).status_code == 422
    assert profile_email(db, flow) == flow.new
    assert db.execute(
        text("SELECT count(*) FROM data_deletion_requests WHERE user_id=:uid"),
        {"uid": flow.uid},
    ).scalar_one() == 0
