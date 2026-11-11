from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from drugtime.modules.identity.application.email_change import EmailChange
from drugtime.modules.identity.domain.email_change import EmailChangeState
from drugtime.shared.errors import Conflict, DomainError, ServiceUnavailable


class Fixture:
    def __init__(self):
        self.uid = uuid4()
        self.state = EmailChangeState()
        self.profile = "old@example.test"
        self.auth_email = self.profile
        self.outbox = []
        self.at = datetime(2026, 11, 11, tzinfo=UTC)
        self.fail_db = False
        self.fail_auth_after_update = False
        self.deleted_otp_invalidated = False
        self.service = EmailChange(self.lock, self, self, self.send, lambda: self.at, b"k" * 32)

    @contextmanager
    def lock(self, uid):
        assert uid == self.uid
        yield self

    @contextmanager
    def begin(self):
        before = (self.state, self.profile, self.deleted_otp_invalidated)
        try:
            yield
        except Exception:
            self.state, self.profile, self.deleted_otp_invalidated = before
            raise

    def state(self, conn, uid):
        return self.state

    def save(self, conn, uid, state):
        self.state = state

    def profile_email(self, conn, uid):
        return self.profile

    def email_in_use(self, conn, uid, email):
        return email == "taken@example.test"

    def verified_email(self, uid):
        return self.auth_email

    def update_email(self, uid, email):
        self.auth_email = email
        if self.fail_auth_after_update:
            raise ServiceUnavailable("service_unavailable")

    def finish(self, conn, uid, state):
        if self.fail_db:
            raise RuntimeError("simulated database failure")
        assert self.profile == state.old_email
        self.profile = state.new_email
        self.invalidate_deletion(conn, uid)

    def invalidate_deletion(self, conn, uid):
        self.deleted_otp_invalidated = True

    def send(self, email, otp):
        self.outbox.append((email, otp))


def scenario():
    f = Fixture()
    # Keep the callable state accessor separate from its stored value.
    from types import SimpleNamespace

    store = SimpleNamespace(
        state=lambda conn, uid: f.state,
        save=f.save,
        profile_email=f.profile_email,
        email_in_use=f.email_in_use,
        finish=f.finish,
        invalidate_deletion=f.invalidate_deletion,
    )
    f.service = replace(f.service, store=store)
    return f


def test_email_change_requires_proof_of_both_addresses():
    f = scenario()
    challenge, expires = f.service.start(f.uid, " New@Example.Test ")
    assert expires == f.at + timedelta(minutes=5)
    assert f.outbox[-1][0] == "old@example.test"
    old_otp = f.outbox[-1][1]
    with pytest.raises(DomainError, match="email_change_otp_invalid"):
        f.service.confirm(f.uid, challenge, old_otp)
    assert f.profile == f.auth_email == "old@example.test"
    assert f.service.verify_current(f.uid, challenge, old_otp)[0] == challenge
    assert f.outbox[-1][0] == "new@example.test"
    new_otp = f.outbox[-1][1]
    with pytest.raises(DomainError, match="email_change_otp_invalid"):
        f.service.verify_current(f.uid, challenge, old_otp)
    f.service.confirm(f.uid, challenge, new_otp)
    assert f.profile == f.auth_email == "new@example.test"
    assert f.deleted_otp_invalidated and f.state.stage == "done"
    with pytest.raises(DomainError, match="email_change_otp_invalid"):
        f.service.confirm(f.uid, challenge, new_otp)


def test_uncertain_auth_update_blocks_until_reconciled():
    f = scenario()
    challenge, _ = f.service.start(f.uid, "new@example.test")
    f.service.verify_current(f.uid, challenge, f.outbox[-1][1])
    f.fail_auth_after_update = True
    with pytest.raises(ServiceUnavailable):
        f.service.confirm(f.uid, challenge, f.outbox[-1][1])
    assert f.state.stage == "applying" and f.profile == "old@example.test"
    with pytest.raises(ServiceUnavailable):
        f.service.start(f.uid, "new@example.test")
    f.service.reconcile(f.uid)
    assert f.state.stage == "done" and f.profile == f.auth_email == "new@example.test"
    assert f.deleted_otp_invalidated


def test_database_failure_after_auth_update_keeps_marker_until_recovery():
    f = scenario()
    challenge, _ = f.service.start(f.uid, "new@example.test")
    f.service.verify_current(f.uid, challenge, f.outbox[-1][1])
    f.fail_db = True
    with pytest.raises(ServiceUnavailable, match="service_unavailable"):
        f.service.confirm(f.uid, challenge, f.outbox[-1][1])
    assert f.state.stage == "applying"
    assert f.profile == "old@example.test" and f.auth_email == "new@example.test"
    with pytest.raises(ServiceUnavailable, match="service_unavailable"):
        f.service.start(f.uid, "other@example.test")
    f.fail_db = False
    f.service.reconcile(f.uid)
    assert f.profile == f.auth_email == "new@example.test"
    assert f.state.stage == "done" and f.deleted_otp_invalidated


def test_email_change_rejects_mismatch_and_expired_codes():
    f = scenario()
    with pytest.raises(Conflict, match="email_change_unavailable"):
        f.service.start(f.uid, "taken@example.test")
    challenge, _ = f.service.start(f.uid, "new@example.test")
    f.at += timedelta(minutes=5)
    with pytest.raises(DomainError, match="email_change_otp_invalid"):
        f.service.verify_current(f.uid, challenge, f.outbox[-1][1])
    assert f.state.stage == "old" and f.profile == "old@example.test"
