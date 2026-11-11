from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
from sqlalchemy.exc import DBAPIError

from drugtime.modules.consent.adapters.outbound.sql_deletion_creation import SqlDeletionCreation
from drugtime.modules.consent.application.create_deletion_request import DeletionCreation
from drugtime.modules.consent.domain.deletion_creation import DeletionOtpState
from drugtime.shared.errors import Conflict, DomainError, ServiceUnavailable, TooManyRequests


def test_deletion_lock_has_local_timeout_and_translates_lock_unavailable():
    class LockUnavailable(Exception):
        sqlstate = "55P03"

    connection = Mock()
    connection.execute.side_effect = [None, DBAPIError(None, None, LockUnavailable())]
    with pytest.raises(ServiceUnavailable, match="service_unavailable"):
        SqlDeletionCreation().lock(SimpleNamespace(connection=connection), uuid4())
    timeout_call, lock_call = connection.execute.call_args_list
    assert str(timeout_call.args[0]) == "SET LOCAL lock_timeout = '5s'"
    assert "pg_advisory_xact_lock" in str(lock_call.args[0])


class Store:
    def __init__(self):
        self.states = {}
        self.requests = {}
        self.fail_insert = False

    @contextmanager
    def transaction(self):
        states, requests = self.states.copy(), self.requests.copy()
        try:
            yield self
        except Exception:
            self.states, self.requests = states, requests
            raise

    def lock(self, uow, user_id):
        pass

    def otp_state(self, uow, user_id):
        return self.states.get(user_id, DeletionOtpState())

    def save_otp(self, uow, user_id, state):
        self.states[user_id] = state

    def pending(self, uow, user_id):
        return self.requests.get(user_id)

    def insert(self, uow, user_id, request):
        if self.fail_insert:
            raise RuntimeError("database unavailable")
        assert user_id not in self.requests
        self.requests[user_id] = request


class Scenario:
    def __init__(self):
        self.store = Store()
        self.uid = uuid4()
        self.email = "member@example.test"
        self.at = datetime(2026, 11, 11, 3, tzinfo=UTC)
        self.mail = []
        self.fail_mail = False
        self.service = DeletionCreation(
            self.store.transaction,
            self.store,
            lambda uid: self.email,
            self.send_mail,
            lambda: self.at,
            b"unit-test-key" * 3,
            lambda uow, uid: False,
        )

    def send_mail(self, email, otp):
        if self.fail_mail:
            raise ServiceUnavailable("service_unavailable")
        self.mail.append((email, otp))

    def issue(self):
        challenge, expiry = self.service.issue(self.uid)
        assert expiry == self.at + timedelta(minutes=5)
        return challenge, self.mail[-1][1]


def test_one_use_and_fresh_otp_retry_preserve_the_deadline():
    s = Scenario()
    challenge, otp = s.issue()
    assert not s.store.requests and s.mail[-1][0] == s.email
    pending, created = s.service.confirm(s.uid, challenge, otp)
    assert created and pending.scheduled_deletion_at - pending.requested_at == timedelta(days=30)
    with pytest.raises(DomainError, match="deletion_otp_invalid"):
        s.service.confirm(s.uid, challenge, otp)
    s.at += timedelta(minutes=1)
    assert s.service.confirm(s.uid, *s.issue()) == (pending, False)
    s.at = pending.scheduled_deletion_at
    new = s.issue()
    with pytest.raises(Conflict, match="deletion_request_due"):
        s.service.confirm(s.uid, *new)
    assert s.store.requests == {s.uid: pending}


def test_wrong_account_changed_email_and_expired_challenge_do_not_create_request():
    s = Scenario()
    challenge, otp = s.issue()
    with pytest.raises(DomainError, match="deletion_otp_invalid"):
        s.service.confirm(uuid4(), challenge, otp)
    s.email = "changed@example.test"
    with pytest.raises(DomainError, match="deletion_otp_invalid"):
        s.service.confirm(s.uid, challenge, otp)
    s.email = "member@example.test"
    s.at += timedelta(minutes=5)
    with pytest.raises(DomainError, match="deletion_otp_invalid"):
        s.service.confirm(s.uid, challenge, otp)
    assert not s.store.requests


def test_resend_does_not_clear_attempt_limits_or_accept_old_challenge():
    s = Scenario()
    old = s.issue()
    with pytest.raises(TooManyRequests):
        s.issue()
    s.at += timedelta(minutes=1)
    new = s.issue()
    for _ in range(5):
        with pytest.raises(DomainError, match="deletion_otp_invalid"):
            s.service.confirm(s.uid, *old)
    with pytest.raises(TooManyRequests, match="deletion_otp_rate_limited"):
        s.service.confirm(s.uid, *new)
    with pytest.raises(TooManyRequests):
        s.issue()
    assert s.store.states[s.uid].failure_count == 5


def test_delivery_failure_keeps_previous_challenge_and_consumes_send_budget():
    s = Scenario()
    old = s.issue()
    s.at += timedelta(minutes=1)
    s.fail_mail = True
    with pytest.raises(ServiceUnavailable):
        s.issue()
    assert s.store.states[s.uid].send_count == 2
    assert s.service.confirm(s.uid, *old)[1]


def test_write_failure_does_not_consume_the_challenge():
    s = Scenario()
    issued = s.issue()
    s.store.fail_insert = True
    with pytest.raises(RuntimeError):
        s.service.confirm(s.uid, *issued)
    assert not s.store.requests and s.store.states[s.uid].consumed_at is None
    s.store.fail_insert = False
    assert s.service.confirm(s.uid, *issued)[1]
