from uuid import uuid4

import pytest

from drugtime.modules.access.application.authorize import authorize
from drugtime.modules.access.domain.rules import AccessFacts, Action, ActorRole, Scope
from drugtime.shared.errors import Forbidden

P, C = uuid4(), uuid4()


class Facts:
    def __init__(self, **kw):
        self.f = AccessFacts(
            caller_id=C,
            patient_id=P,
            caller_is_admin=False,
            purpose_consent=True,
            active_sharing_link=True,
            family_sharing_consent=True,
        )
        self.f = AccessFacts(**{**self.f.__dict__, **kw})

    def read(self, uow, caller_id, caller_is_admin, patient_id, scope):
        return self.f


class Log:
    def __init__(self, fail_allowed=False):
        self.allowed, self.denied, self.fail_allowed = [], [], fail_allowed

    def append_allowed(self, uow, actor_id, role, patient_id, scope):
        if self.fail_allowed:
            raise RuntimeError("access_logs unavailable")
        self.allowed.append((actor_id, role, patient_id, scope))

    def append_denied(self, actor_id, role, patient_id, scope, reason):
        self.denied.append((actor_id, role, patient_id, scope, reason))


def _call(facts, log, action=Action.READ):
    authorize(
        object(),
        facts,
        log,
        caller_id=C,
        caller_is_admin=facts.f.caller_is_admin,
        patient_id=P,
        scope=Scope.MEDICATIONS,
        action=action,
    )


def test_allowed_log_failure_fails_request():
    with pytest.raises(RuntimeError):
        _call(Facts(), Log(fail_allowed=True))


def test_family_read_appends_allowed():
    log = Log()
    _call(Facts(), log)
    assert log.allowed == [(C, ActorRole.FAMILY, P, Scope.MEDICATIONS)] and log.denied == []


def test_denied_write_appends_denied_and_raises():
    log = Log()
    with pytest.raises(Forbidden, match="khong_co_quyen"):
        _call(Facts(), log, Action.WRITE)
    assert log.allowed == []
    assert log.denied == [(C, ActorRole.FAMILY, P, Scope.MEDICATIONS, "khong_co_quyen")]
