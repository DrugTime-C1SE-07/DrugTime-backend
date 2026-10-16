from datetime import UTC, datetime
from uuid import uuid4

import pytest

from drugtime.modules.family.domain.link import (
    FamilyLink,
    FamilyLinkError,
    LinkStatus,
    ensure_can_create_link,
    pending_link,
    transition_link,
)


def test_create_link_request_rejects_self_link__AC4():
    user_id = uuid4()

    with pytest.raises(FamilyLinkError) as exc:
        pending_link(user_id, user_id)

    assert exc.value.code == "self_link_not_allowed"


def test_reversed_patient_family_pair_is_not_same_link__AC6():
    patient_id = uuid4()
    family_id = uuid4()
    existing = pending_link(patient_id, family_id)

    ensure_can_create_link(family_id, patient_id, existing=None)

    assert existing.patient_user_id == patient_id
    assert existing.family_user_id == family_id


def test_pending_to_active_is_allowed__AC7():
    link = pending_link(uuid4(), uuid4())

    updated = transition_link(link, LinkStatus.ACTIVE, now=datetime(2026, 10, 7, tzinfo=UTC))

    assert updated.status is LinkStatus.ACTIVE
    assert updated.revoked_at is None


def test_active_to_revoked_sets_revoked_at__AC8():
    now = datetime(2026, 10, 7, 8, 30, tzinfo=UTC)
    link = FamilyLink(
        id=1,
        patient_user_id=uuid4(),
        family_user_id=uuid4(),
        status=LinkStatus.ACTIVE,
        sharing_enabled=True,
    )

    updated = transition_link(link, LinkStatus.REVOKED, now=now)

    assert updated.status is LinkStatus.REVOKED
    assert updated.revoked_at == now
    assert updated.sharing_enabled is True


def test_pending_to_rejected_sets_rejected_at():
    now = datetime(2026, 10, 7, 8, 45, tzinfo=UTC)
    link = pending_link(uuid4(), uuid4())

    updated = transition_link(link, LinkStatus.REJECTED, now=now)

    assert updated.status is LinkStatus.REJECTED
    assert updated.revoked_at is None
    assert updated.rejected_at == now


def test_revoked_cannot_be_approved_directly__AC9():
    link = FamilyLink(
        id=1,
        patient_user_id=uuid4(),
        family_user_id=uuid4(),
        status=LinkStatus.REVOKED,
        revoked_at=datetime(2026, 10, 7, tzinfo=UTC),
    )

    with pytest.raises(FamilyLinkError) as exc:
        transition_link(link, LinkStatus.ACTIVE, now=datetime(2026, 10, 8, tzinfo=UTC))

    assert exc.value.code == "invalid_link_transition"


def test_invalid_transition_is_rejected__AC10():
    link = pending_link(uuid4(), uuid4())

    with pytest.raises(FamilyLinkError) as exc:
        transition_link(link, LinkStatus.REVOKED, now=datetime(2026, 10, 7, tzinfo=UTC))

    assert exc.value.code == "invalid_link_transition"


def test_rejected_cannot_be_approved_directly():
    link = FamilyLink(
        id=1,
        patient_user_id=uuid4(),
        family_user_id=uuid4(),
        status=LinkStatus.REJECTED,
        rejected_at=datetime(2026, 10, 7, tzinfo=UTC),
    )

    with pytest.raises(FamilyLinkError) as exc:
        transition_link(link, LinkStatus.ACTIVE, now=datetime(2026, 10, 8, tzinfo=UTC))

    assert exc.value.code == "invalid_link_transition"


@pytest.mark.parametrize("target", [LinkStatus.ACTIVE, LinkStatus.REJECTED])
def test_pending_decisions_clear_sharing_but_preserve_request_time(target):
    now = datetime(2026, 10, 15, tzinfo=UTC)
    requested = datetime(2026, 10, 14, tzinfo=UTC)
    link = FamilyLink(1, uuid4(), uuid4(), LinkStatus.PENDING, True, requested)
    result = transition_link(link, target, now=now)
    assert result.sharing_enabled is False
    assert result.linked_at == requested
    assert result.rejected_at == (now if target is LinkStatus.REJECTED else None)
