from itertools import product
from uuid import uuid4

from drugtime.modules.access.domain.rules import AccessFacts, Action, ActorRole, decide

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


def _old_decide(f):
    """Bản decide trước task 2.01, để chứng minh Action.READ không đổi hành vi."""
    if f.caller_id == f.patient_id:
        return (f.purpose_consent, None, None if f.purpose_consent else "consent_revoked")
    if f.active_sharing_link and f.family_sharing_consent and f.purpose_consent:
        return (True, ActorRole.FAMILY, None)
    if f.caller_is_admin:
        return (True, ActorRole.ADMIN, None)
    return (False, ActorRole.NO_ACCESS, "khong_co_quyen")


def test_read_decisions_unchanged():
    for bits in product((False, True), repeat=5):
        is_self, admin, purpose, link, family = bits
        f = facts(
            caller_id=P if is_self else C,
            caller_is_admin=admin,
            purpose_consent=purpose,
            active_sharing_link=link,
            family_sharing_consent=family,
        )
        d = decide(f, Action.READ)
        assert (d.allowed, d.log_role, d.reason) == _old_decide(f), bits
        assert decide(f) == d


def test_write_allows_only_self_with_consent():
    assert decide(facts(caller_id=P), Action.WRITE) == decide(facts(caller_id=P))
    d = decide(facts(caller_id=P, purpose_consent=False), Action.WRITE)
    assert not d.allowed and d.log_role is None and d.reason == "consent_revoked"


def test_write_denies_linked_family_and_admin_with_their_role():
    d = decide(facts(), Action.WRITE)
    assert not d.allowed and d.log_role is ActorRole.FAMILY and d.reason == "khong_co_quyen"
    d = decide(facts(active_sharing_link=False, caller_is_admin=True), Action.WRITE)
    assert not d.allowed and d.log_role is ActorRole.ADMIN and d.reason == "khong_co_quyen"
    d = decide(facts(active_sharing_link=False), Action.WRITE)
    assert not d.allowed and d.log_role is ActorRole.NO_ACCESS and d.reason == "khong_co_quyen"
