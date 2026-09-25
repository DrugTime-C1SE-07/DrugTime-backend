from uuid import uuid4

from drugtime.modules.access.domain.rules import AccessFacts, ActorRole, decide

P, C = uuid4(), uuid4()


def facts(**kw):
    base = dict(
        caller_id=C,
        patient_id=P,
        caller_is_admin=False,
        purpose_consent=True,
        active_sharing_link=True,
        family_sharing_consent=True,
    )
    return AccessFacts(**{**base, **kw})


def test_self_access_is_not_logged_and_follows_purpose_consent():
    assert decide(facts(caller_id=P)).log_role is None
    assert decide(facts(caller_id=P)).allowed
    assert not decide(facts(caller_id=P, purpose_consent=False)).allowed


def test_family_needs_link_sharing_and_consents():
    assert decide(facts()).log_role is ActorRole.FAMILY
    for missing in ("active_sharing_link", "family_sharing_consent", "purpose_consent"):
        d = decide(facts(**{missing: False}))
        assert not d.allowed and d.log_role is ActorRole.NO_ACCESS


def test_admin_is_logged():
    d = decide(facts(active_sharing_link=False, caller_is_admin=True))
    assert d.allowed and d.log_role is ActorRole.ADMIN
