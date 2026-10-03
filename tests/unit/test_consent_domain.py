from datetime import UTC, datetime

import pytest

from drugtime.modules.consent.domain.consent import (
    CURRENT_DOCUMENT_VERSION,
    DOCUMENT_OUTDATED,
    ActiveConsent,
    check_document_version,
    states_for,
)
from drugtime.modules.consent.domain.purpose import Purpose
from drugtime.shared.errors import DomainError

ACTIVE = ActiveConsent(datetime(2026, 10, 3, 10, 0, tzinfo=UTC), "2026-10-v1")


def test_states_for_always_returns_three_in_order():
    states = states_for({})
    assert [s.purpose for s in states] == [
        Purpose.HEALTH_DATA,
        Purpose.FAMILY_SHARING,
        Purpose.AI_MEAL,
    ]
    assert all(s.active is None for s in states)
    assert [s.current_document_version for s in states] == ["2026-10-v1"] * 3


def test_states_for_keeps_only_given_purposes_active():
    states = states_for({Purpose.FAMILY_SHARING: ACTIVE})
    assert [s.active for s in states] == [None, ACTIVE, None]


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
