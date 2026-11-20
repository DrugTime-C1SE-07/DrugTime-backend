from datetime import timedelta

import pytest

from drugtime.shared.errors import Conflict, DomainError
from tests.unit.test_deletion_creation_otp import Scenario


def test_verify_has_no_side_effect_until_final_confirmation():
    s = Scenario()
    challenge, otp = s.issue()
    s.service.confirm(s.uid, challenge, otp, verify_only=True)
    assert not s.store.requests
    assert s.store.states[s.uid].consumed_at is None
    assert s.service.confirm(s.uid, challenge, otp)[1]


def test_cancel_retries_do_not_recreate_links_consents_or_allow_consumed_otp():
    s = Scenario()
    proof = s.issue()
    saved, _ = s.service.confirm(s.uid, *proof)
    s.store.cancel = lambda uow, uid, at: s.store.requests.pop(uid)
    assert s.service.current(s.uid) == saved
    s.at += timedelta(minutes=1)
    s.service.cancel(s.uid)
    s.service.cancel(s.uid)
    assert s.service.current(s.uid) is None
    with pytest.raises(DomainError):
        s.service.confirm(s.uid, *proof)


def test_deadline_is_exclusive_and_lookup_never_cancels():
    s = Scenario()
    saved, _ = s.service.confirm(s.uid, *s.issue())
    s.at = saved.scheduled_deletion_at
    assert s.service.current(s.uid) == saved
    with pytest.raises(Conflict, match="deletion_request_due"):
        s.service.cancel(s.uid)
    assert s.service.current(s.uid) == saved
