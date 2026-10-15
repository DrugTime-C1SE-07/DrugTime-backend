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
from drugtime.shared.errors import Forbidden, NotFound


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
        sharing_enabled = False if status == LinkStatus.REVOKED else link.sharing_enabled
        updated = FamilyLink(
            id=link.id,
            patient_user_id=link.patient_user_id,
            family_user_id=link.family_user_id,
            status=status,
            sharing_enabled=sharing_enabled,
            linked_at=link.linked_at,
            revoked_at=revoked_at,
            rejected_at=rejected_at,
        )
        self.links[link_id] = updated
        self.updated.append(updated)
        return updated

    def revoke(self, uow, *, link_id, caller_id, now):
        link = self.links.get(link_id)
        if link is None:
            return None
        if caller_id != link.patient_user_id and caller_id != link.family_user_id:
            return None
        updated = FamilyLink(
            id=link.id,
            patient_user_id=link.patient_user_id,
            family_user_id=link.family_user_id,
            status=LinkStatus.REVOKED,
            sharing_enabled=False,
            linked_at=link.linked_at,
            revoked_at=link.revoked_at or now,
            rejected_at=link.rejected_at,
        )
        self.links[link_id] = updated
        self.updated.append(updated)
        return updated

    def has_active_sharing_link(self, uow, patient_id, family_id):
        for link in self.links.values():
            if (
                link.patient_user_id == patient_id
                and link.family_user_id == family_id
                and link.status == LinkStatus.ACTIVE
                and link.sharing_enabled
            ):
                return True
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
    patient_id = uuid4()
    family_id = uuid4()
    link = FamilyLink(1, patient_id, family_id, LinkStatus.ACTIVE, sharing_enabled=True)
    links = FakeLinks([link])

    result = revoke_link(object(), link_id=1, caller_id=patient_id, now=now, links=links)

    assert result.status is LinkStatus.REVOKED
    assert result.sharing_enabled is False
    assert result.revoked_at == now
    assert links.updated == [result]


def test_revoke_link_by_family_self_leave():
    now = datetime(2026, 10, 7, tzinfo=UTC)
    patient_id = uuid4()
    family_id = uuid4()
    link = FamilyLink(1, patient_id, family_id, LinkStatus.ACTIVE, sharing_enabled=True)
    links = FakeLinks([link])

    result = revoke_link(object(), link_id=1, caller_id=family_id, now=now, links=links)

    assert result.status is LinkStatus.REVOKED
    assert result.sharing_enabled is False
    assert result.revoked_at == now
    assert links.updated == [result]


def test_revoke_link_by_stranger_raises_forbidden():
    now = datetime(2026, 10, 7, tzinfo=UTC)
    patient_id = uuid4()
    family_id = uuid4()
    stranger_id = uuid4()
    link = FamilyLink(1, patient_id, family_id, LinkStatus.ACTIVE, sharing_enabled=True)
    links = FakeLinks([link])

    with pytest.raises(Forbidden) as exc:
        revoke_link(object(), link_id=1, caller_id=stranger_id, now=now, links=links)

    assert exc.value.args[0] == "khong_co_quyen"
    assert not links.updated


def test_revoke_non_existent_link_raises_forbidden():
    now = datetime(2026, 10, 7, tzinfo=UTC)
    links = FakeLinks([])

    with pytest.raises(Forbidden) as exc:
        revoke_link(object(), link_id=999, caller_id=uuid4(), now=now, links=links)

    assert exc.value.args[0] == "khong_co_quyen"
    assert not links.updated


def test_revoke_pending_link_updates_to_revoked():
    now = datetime(2026, 10, 7, tzinfo=UTC)
    patient_id = uuid4()
    family_id = uuid4()
    link = FamilyLink(1, patient_id, family_id, LinkStatus.PENDING, sharing_enabled=False)
    links = FakeLinks([link])

    result = revoke_link(object(), link_id=1, caller_id=patient_id, now=now, links=links)

    assert result.status is LinkStatus.REVOKED
    assert result.sharing_enabled is False
    assert result.revoked_at == now
    assert links.updated == [result]


def test_revoke_already_revoked_link_idempotent():
    first_now = datetime(2026, 10, 7, 10, 0, tzinfo=UTC)
    second_now = datetime(2026, 10, 7, 11, 0, tzinfo=UTC)
    patient_id = uuid4()
    family_id = uuid4()
    link = FamilyLink(
        1, patient_id, family_id, LinkStatus.REVOKED, sharing_enabled=False, revoked_at=first_now
    )
    links = FakeLinks([link])

    result = revoke_link(object(), link_id=1, caller_id=patient_id, now=second_now, links=links)

    assert result.status is LinkStatus.REVOKED
    assert result.revoked_at == first_now
    assert links.updated == []


def test_after_revoke_access_control_denies_and_logs():
    now = datetime(2026, 10, 7, tzinfo=UTC)
    patient_id = uuid4()
    family_id = uuid4()
    link = FamilyLink(1, patient_id, family_id, LinkStatus.ACTIVE, sharing_enabled=True)
    links = FakeLinks([link])

    assert links.has_active_sharing_link(object(), patient_id, family_id) is True

    revoke_link(object(), link_id=1, caller_id=family_id, now=now, links=links)

    assert links.has_active_sharing_link(object(), patient_id, family_id) is False

    from drugtime.modules.access.application.authorize import authorize
    from drugtime.modules.access.domain.rules import AccessFacts, Action, ActorRole, Scope

    class Facts:
        def read(self, uow, caller_id, caller_is_admin, patient_id, scope):
            return AccessFacts(
                caller_id=caller_id,
                patient_id=patient_id,
                caller_is_admin=caller_is_admin,
                purpose_consent=True,
                active_sharing_link=links.has_active_sharing_link(uow, patient_id, caller_id),
                family_sharing_consent=True,
            )

    class Log:
        def __init__(self):
            self.denied = []
            self.allowed = []

        def append_allowed(self, uow, actor_id, role, patient_id, scope):
            self.allowed.append((actor_id, role, patient_id, scope))

        def append_denied(self, actor_id, role, patient_id, scope, reason):
            self.denied.append((actor_id, role, patient_id, scope, reason))

    log = Log()
    with pytest.raises(Forbidden) as exc:
        authorize(
            object(),
            Facts(),
            log,
            caller_id=family_id,
            caller_is_admin=False,
            patient_id=patient_id,
            scope=Scope.MEDICATIONS,
            action=Action.READ,
        )

    assert exc.value.args[0] == "khong_co_quyen"
    assert len(log.denied) == 1
    assert log.denied[0][1] is ActorRole.NO_ACCESS
    assert log.denied[0][4] == "khong_co_quyen"


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
    patient_id = uuid4()
    link = FamilyLink(1, patient_id, uuid4(), LinkStatus.REJECTED)
    links = FakeLinks([link])

    with pytest.raises(FamilyLinkError):
        revoke_link(object(), link_id=1, caller_id=patient_id, now=datetime(2026, 10, 7, tzinfo=UTC), links=links)

    assert not links.updated


