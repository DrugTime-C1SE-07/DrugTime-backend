from datetime import UTC, datetime

import pytest

from drugtime.modules.consent.domain.consent import (
    CURRENT_DOCUMENT_VERSION,
    DOCUMENT_OUTDATED,
    NOT_WITHDRAWABLE,
    ActiveConsent,
    check_document_version,
    check_withdrawable,
    grant_action,
    states_for,
)
from drugtime.modules.consent.domain.purpose import Purpose
from drugtime.shared.errors import DomainError

ACTIVE = ActiveConsent(datetime(2026, 10, 3, 10, 0, tzinfo=UTC), "2026-10-v1")


def test_states_for_lists_four_purposes_in_contract_order():
    states = states_for({})
    assert [s.purpose for s in states] == [
        Purpose.HEALTH_DATA,
        Purpose.FAMILY_SHARING,
        Purpose.AI_MEAL,
        Purpose.TERMS,
    ]
    assert all(s.active is None for s in states)
    assert [s.current_document_version for s in states] == ["2026-10-v1"] * 4


def test_states_for_keeps_only_given_purposes_active():
    states = states_for({Purpose.FAMILY_SHARING: ACTIVE})
    assert [s.active for s in states] == [None, ACTIVE, None, None]


def test_every_purpose_has_a_current_version():
    assert set(CURRENT_DOCUMENT_VERSION) == set(Purpose)


@pytest.mark.parametrize("purpose", list(Purpose))
def test_check_document_version_accepts_current(purpose):
    check_document_version(purpose, CURRENT_DOCUMENT_VERSION[purpose])


@pytest.mark.parametrize("version", ["2026-09-v0", "", "2026-10-V1", " 2026-10-v1"])
def test_check_document_version_rejects_other_version(version):
    with pytest.raises(DomainError) as exc:
        check_document_version(Purpose.HEALTH_DATA, version)
    assert str(exc.value) == DOCUMENT_OUTDATED


OUTDATED = ActiveConsent(datetime(2026, 9, 1, 10, 0, tzinfo=UTC), "2026-09-v0")


@pytest.mark.parametrize("purpose", list(Purpose))
def test_grant_action_inserts_when_nothing_active(purpose):
    assert grant_action(purpose, None, "2026-10-v1") == "insert"


@pytest.mark.parametrize("purpose", list(Purpose))
def test_grant_action_keeps_same_version(purpose):
    assert grant_action(purpose, ACTIVE, "2026-10-v1") == "keep"


def test_grant_action_replaces_outdated_terms():
    assert grant_action(Purpose.TERMS, OUTDATED, "2026-10-v1") == "replace"


@pytest.mark.parametrize("purpose", [Purpose.HEALTH_DATA, Purpose.FAMILY_SHARING, Purpose.AI_MEAL])
def test_grant_action_keeps_outdated_other_purposes(purpose):
    # Đồng ý lại theo phiên bản cho các mục đích này là task riêng; giữ hành vi 1.14.
    assert grant_action(purpose, OUTDATED, "2026-10-v1") == "keep"


def test_terms_not_withdrawable():
    with pytest.raises(DomainError) as exc:
        check_withdrawable(Purpose.TERMS)
    assert str(exc.value) == NOT_WITHDRAWABLE == "consent_not_withdrawable"


@pytest.mark.parametrize("purpose", [Purpose.HEALTH_DATA, Purpose.FAMILY_SHARING, Purpose.AI_MEAL])
def test_other_purposes_withdrawable(purpose):
    check_withdrawable(purpose)
