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


def test_unknown_patient_raises_forbidden_without_log():
    for admin in (False, True):
        log = Log()
        with pytest.raises(Forbidden, match="khong_co_quyen"):
            _call(Facts(patient_exists=False, caller_is_admin=admin), log)
        assert log.allowed == [] and log.denied == []


def test_admin_read_denied_logged__QD32():
    log = Log()
    with pytest.raises(Forbidden, match="khong_co_quyen"):
        _call(Facts(caller_is_admin=True, active_sharing_link=False), log)
    assert log.allowed == []
    assert log.denied == [(C, ActorRole.ADMIN, P, Scope.MEDICATIONS, "khong_co_quyen")]


@pytest.mark.parametrize("action", [Action.READ, Action.WRITE])
@pytest.mark.parametrize("consent", [True, False])
def test_profile_self_audit_and_consent(action, consent):
    facts = Facts(caller_id=P, purpose_consent=consent)
    log = Log()

    def call():
        authorize(
            object(),
            facts,
            log,
            caller_id=P,
            caller_is_admin=False,
            patient_id=P,
            scope=Scope.HEALTH_PROFILE,
            action=action,
        )

    if consent:
        call()
        assert log.allowed == [(P, ActorRole.PATIENT, P, Scope.HEALTH_PROFILE)]
        assert log.denied == []
    else:
        with pytest.raises(Forbidden, match="consent_revoked"):
            call()
        assert log.allowed == []
        assert log.denied == [(P, ActorRole.PATIENT, P, Scope.HEALTH_PROFILE, "consent_revoked")]


@pytest.mark.parametrize("consent", [True, False])
def test_profile_self_audit_failure_fails_closed(consent):
    log = Log(fail_allowed=True)
    if not consent:

        def fail_denied(*args):
            raise RuntimeError("audit unavailable")

        log.append_denied = fail_denied
    with pytest.raises(RuntimeError):
        authorize(
            object(),
            Facts(caller_id=P, purpose_consent=consent),
            log,
            caller_id=P,
            caller_is_admin=False,
            patient_id=P,
            scope=Scope.HEALTH_PROFILE,
        )


@pytest.mark.parametrize("consent", [True, False])
@pytest.mark.parametrize("audit_self", [True, False])
@pytest.mark.parametrize("scope", [Scope.ADHERENCE, Scope.HEALTH_PROFILE])
def test_explicit_self_audit_and_mandatory_profile_audit(consent, audit_self, scope):
    log = Log()

    def call():
        authorize(
            object(),
            Facts(caller_id=P, purpose_consent=consent),
            log,
            caller_id=P,
            caller_is_admin=False,
            patient_id=P,
            scope=scope,
            audit_self=audit_self,
        )

    if consent:
        call()
    else:
        with pytest.raises(Forbidden, match="consent_revoked"):
            call()
    expected = audit_self or scope is Scope.HEALTH_PROFILE
    assert bool(log.allowed or log.denied) is expected
    if expected:
        assert (log.allowed or log.denied)[0][1] is ActorRole.PATIENT


@pytest.mark.parametrize("consent", [True, False])
def test_adherence_self_audit_failure_fails_closed(consent):
    log = Log(fail_allowed=True)
    if not consent:

        def fail_denied(*args):
            raise RuntimeError("audit unavailable")

        log.append_denied = fail_denied
    with pytest.raises(RuntimeError):
        authorize(
            object(),
            Facts(caller_id=P, purpose_consent=consent),
            log,
            caller_id=P,
            caller_is_admin=False,
            patient_id=P,
            scope=Scope.ADHERENCE,
            audit_self=True,
        )


@pytest.mark.parametrize(
    "change",
    [
        {"active_sharing_link": False},
        {"purpose_consent": False},
        {"family_sharing_consent": False},
        {"caller_is_admin": True, "active_sharing_link": False},
    ],
)
def test_explicit_audit_does_not_grant_access(change):
    log = Log()
    with pytest.raises(Forbidden, match="khong_co_quyen"):
        authorize(
            object(),
            Facts(**change),
            log,
            caller_id=C,
            caller_is_admin=change.get("caller_is_admin", False),
            patient_id=P,
            scope=Scope.ADHERENCE,
            audit_self=True,
        )
    assert len(log.denied) == 1 and not log.allowed


def test_existing_adherence_caller_default_does_not_audit_self():
    log = Log()
    authorize(
        object(),
        Facts(caller_id=P),
        log,
        caller_id=P,
        caller_is_admin=False,
        patient_id=P,
        scope=Scope.ADHERENCE,
    )
    assert not log.allowed and not log.denied


def test_history_adapter_requests_audit_without_changing_post(monkeypatch):
    from drugtime.modules.adherence.adapters.outbound import other_modules as adapter

    calls = []
    monkeypatch.setattr(adapter.access, "authorize", lambda *args, **kw: calls.append(kw))
    guard = adapter.AccessGuardAdapter()
    guard.authorize_history(object(), C, False, P)
    guard.authorize_adherence(object(), C, False, P)
    assert calls[0] == dict(
        caller_id=C,
        caller_is_admin=False,
        patient_id=P,
        scope=Scope.ADHERENCE,
        action=Action.READ,
        audit_self=True,
    )
    assert "audit_self" not in calls[1]


def test_public_access_api_forwards_audit_self(monkeypatch):
    from drugtime.modules.access import api

    log = Log()
    monkeypatch.setattr(api, "ModuleFactsReader", lambda: Facts(caller_id=P))
    monkeypatch.setattr(api, "SqlAccessLog", lambda: log)
    api.authorize(
        object(),
        caller_id=P,
        caller_is_admin=False,
        patient_id=P,
        scope=Scope.ADHERENCE,
        audit_self=True,
    )
    assert log.allowed == [(P, ActorRole.PATIENT, P, Scope.ADHERENCE)]
