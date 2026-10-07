from datetime import UTC, datetime
from uuid import uuid4

import pytest

from drugtime.modules.family.application.manage_links import (
    approve_link,
    create_link_request,
    reject_link,
    revoke_link,
)
from drugtime.modules.family.domain.link import FamilyLink, FamilyLinkError, LinkStatus


class FakeLinks:
    def __init__(self, links=None):
        self.links = {link.id: link for link in links or []}
        self.created = []
        self.updated = []
        self.next_id = 100

    def find_by_pair(self, uow, patient_id, family_id):
        for link in self.links.values():
            if link.patient_user_id == patient_id and link.family_user_id == family_id:
                return link
        return None

    def get(self, uow, link_id):
        return self.links.get(link_id)

    def create(self, uow, link):
        saved = FamilyLink(
            id=self.next_id,
            patient_user_id=link.patient_user_id,
            family_user_id=link.family_user_id,
            status=link.status,
            sharing_enabled=link.sharing_enabled,
            linked_at=link.linked_at,
            revoked_at=link.revoked_at,
            rejected_at=link.rejected_at,
        )
        self.next_id += 1
        self.links[saved.id] = saved
        self.created.append(saved)
        return saved

    def update_status(self, uow, link_id, status, revoked_at, rejected_at):
        link = self.links[link_id]
        updated = FamilyLink(
            id=link.id,
            patient_user_id=link.patient_user_id,
            family_user_id=link.family_user_id,
            status=status,
            sharing_enabled=link.sharing_enabled,
            linked_at=link.linked_at,
            revoked_at=revoked_at,
            rejected_at=rejected_at,
        )
        self.links[link_id] = updated
        self.updated.append(updated)
        return updated

    def has_active_sharing_link(self, uow, patient_id, family_id):
        return False

    def sharing_family_ids(self, uow, patient_id):
        return []

    def erase(self, uow, user_id):
        pass


def test_create_link_request_creates_pending_for_new_pair__AC1():
    patient_id = uuid4()
    family_id = uuid4()
    links = FakeLinks()

    result = create_link_request(object(), patient_id=patient_id, family_id=family_id, links=links)

    assert result.status is LinkStatus.PENDING
    assert result.patient_user_id == patient_id
    assert result.family_user_id == family_id
    assert links.created == [result]


def test_same_family_can_link_many_patients__AC2():
    family_id = uuid4()
    links = FakeLinks()

    first = create_link_request(object(), patient_id=uuid4(), family_id=family_id, links=links)
    second = create_link_request(object(), patient_id=uuid4(), family_id=family_id, links=links)

    assert first.family_user_id == second.family_user_id == family_id
    assert first.patient_user_id != second.patient_user_id
    assert len(links.created) == 2


def test_same_patient_can_have_many_family_members__AC3():
    patient_id = uuid4()
    links = FakeLinks()

    first = create_link_request(object(), patient_id=patient_id, family_id=uuid4(), links=links)
    second = create_link_request(object(), patient_id=patient_id, family_id=uuid4(), links=links)

    assert first.patient_user_id == second.patient_user_id == patient_id
    assert first.family_user_id != second.family_user_id
    assert len(links.created) == 2


def test_create_link_request_rejects_self_link_without_writing__AC4():
    user_id = uuid4()
    links = FakeLinks()

    with pytest.raises(FamilyLinkError) as exc:
        create_link_request(object(), patient_id=user_id, family_id=user_id, links=links)

    assert exc.value.code == "self_link_not_allowed"
    assert not links.created


def test_create_link_request_rejects_pending_or_active_duplicate__AC5():
    patient_id = uuid4()
    family_id = uuid4()
    for status in (LinkStatus.PENDING, LinkStatus.ACTIVE):
        links = FakeLinks([FamilyLink(1, patient_id, family_id, status)])

        with pytest.raises(FamilyLinkError) as exc:
            create_link_request(object(), patient_id=patient_id, family_id=family_id, links=links)

        assert exc.value.code == "link_already_exists"
        assert not links.created


def test_approve_link_updates_pending_to_active__AC7():
    link = FamilyLink(1, uuid4(), uuid4(), LinkStatus.PENDING)
    links = FakeLinks([link])

    result = approve_link(
        object(), link_id=1, now=datetime(2026, 10, 7, tzinfo=UTC), links=links
    )

    assert result.status is LinkStatus.ACTIVE
    assert result.revoked_at is None
    assert links.updated == [result]


def test_revoke_link_updates_active_to_revoked__AC8():
    now = datetime(2026, 10, 7, tzinfo=UTC)
    link = FamilyLink(1, uuid4(), uuid4(), LinkStatus.ACTIVE)
    links = FakeLinks([link])

    result = revoke_link(object(), link_id=1, now=now, links=links)

    assert result.status is LinkStatus.REVOKED
    assert result.revoked_at == now
    assert links.updated == [result]


def test_reject_link_updates_pending_to_rejected():
    now = datetime(2026, 10, 7, tzinfo=UTC)
    link = FamilyLink(1, uuid4(), uuid4(), LinkStatus.PENDING)
    links = FakeLinks([link])

    result = reject_link(object(), link_id=1, now=now, links=links)

    assert result.status is LinkStatus.REJECTED
    assert result.revoked_at is None
    assert result.rejected_at == now
    assert links.updated == [result]


def test_revoked_link_cannot_be_approved_directly__AC9():
    link = FamilyLink(1, uuid4(), uuid4(), LinkStatus.REVOKED)
    links = FakeLinks([link])

    with pytest.raises(FamilyLinkError) as exc:
        approve_link(object(), link_id=1, now=datetime(2026, 10, 7, tzinfo=UTC), links=links)

    assert exc.value.code == "invalid_link_transition"
    assert not links.updated


def test_rejected_link_cannot_be_approved_directly():
    link = FamilyLink(1, uuid4(), uuid4(), LinkStatus.REJECTED)
    links = FakeLinks([link])

    with pytest.raises(FamilyLinkError) as exc:
        approve_link(object(), link_id=1, now=datetime(2026, 10, 7, tzinfo=UTC), links=links)

    assert exc.value.code == "invalid_link_transition"
    assert not links.updated


def test_invalid_transition_does_not_write__AC10():
    link = FamilyLink(1, uuid4(), uuid4(), LinkStatus.PENDING)
    links = FakeLinks([link])

    with pytest.raises(FamilyLinkError):
        revoke_link(object(), link_id=1, now=datetime(2026, 10, 7, tzinfo=UTC), links=links)

    assert not links.updated
