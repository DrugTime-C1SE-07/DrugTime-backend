from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

from drugtime.modules.family.application.manage_links import (
    approve_link,
    create_link_request,
    reject_link,
    revoke_link,
    update_sharing,
)
from drugtime.modules.family.domain.consent_confirmation import ConsentConfirmation
from drugtime.modules.family.domain.link import FamilyLink, FamilyLinkError, LinkStatus
from drugtime.shared.errors import Conflict, DomainError, Forbidden, NotFound


class FakeLinks:
    def __init__(self, links=None):
        self.links = {link.id: link for link in links or []}
        self.created = []
        self.updated = []
        self.next_id = 100

    def find_open_by_pair(self, uow, patient_id, family_id):
        for link in self.links.values():
            if (
                link.patient_user_id == patient_id
                and link.family_user_id == family_id
                and link.status in (LinkStatus.PENDING, LinkStatus.ACTIVE)
            ):
                return link
        return None

    def get(self, uow, link_id):
        return self.links.get(link_id)

    def get_for_update(self, uow, link_id):
        return self.get(uow, link_id)

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
            sharing_enabled=False
            if status in (LinkStatus.ACTIVE, LinkStatus.REJECTED)
            else link.sharing_enabled,
            linked_at=link.linked_at,
            revoked_at=revoked_at,
            rejected_at=rejected_at,
        )
        self.links[link_id] = updated
        self.updated.append(updated)
        return updated

    def update_sharing(self, uow, link_id, enabled):
        updated = replace(self.links[link_id], sharing_enabled=enabled)
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
    expected = {LinkStatus.PENDING: "link_request_pending", LinkStatus.ACTIVE: "already_linked"}
    for status, detail in expected.items():
        links = FakeLinks([FamilyLink(1, patient_id, family_id, status)])

        with pytest.raises(Conflict) as exc:
            create_link_request(object(), patient_id=patient_id, family_id=family_id, links=links)

        assert str(exc.value) == detail
        assert not links.created


def test_create_link_request_reopens_rejected_or_revoked_pair__AC9():
    patient_id = uuid4()
    family_id = uuid4()
    for status in (LinkStatus.REJECTED, LinkStatus.REVOKED):
        old = FamilyLink(1, patient_id, family_id, status, sharing_enabled=True)
        links = FakeLinks([old])

        result = create_link_request(
            object(), patient_id=patient_id, family_id=family_id, links=links
        )

        assert result.status is LinkStatus.PENDING
        assert result.sharing_enabled is False
        assert links.links[1] == old


def test_approve_link_updates_pending_to_active__AC7():
    link = FamilyLink(1, uuid4(), uuid4(), LinkStatus.PENDING)
    links = FakeLinks([link])

    result = approved(links).link

    assert result.status is LinkStatus.ACTIVE
    assert result.revoked_at is None
    assert links.updated == [result]


def test_revoke_link_updates_active_to_revoked__AC8():
    link = FamilyLink(1, uuid4(), uuid4(), LinkStatus.ACTIVE)
    links = FakeLinks([link])

    result = revoked(links)

    assert result.status is LinkStatus.REVOKED
    assert result.revoked_at == NOW
    assert links.updated == [result]


def test_reject_link_updates_pending_to_rejected():
    now = datetime(2026, 10, 7, tzinfo=UTC)
    link = FamilyLink(1, uuid4(), uuid4(), LinkStatus.PENDING)
    links = FakeLinks([link])

    result = rejected(links)

    assert result.status is LinkStatus.REJECTED
    assert result.revoked_at is None
    assert result.rejected_at == now
    assert links.updated == [result]


def test_revoked_link_cannot_be_approved_directly__AC9():
    link = FamilyLink(1, uuid4(), uuid4(), LinkStatus.REVOKED)
    links = FakeLinks([link])

    with pytest.raises(Conflict) as exc:
        approved(links)

    assert str(exc.value) == "invalid_link_transition"
    assert not links.updated


def test_rejected_link_cannot_be_approved_directly():
    link = FamilyLink(1, uuid4(), uuid4(), LinkStatus.REJECTED)
    links = FakeLinks([link])

    with pytest.raises(Conflict) as exc:
        approved(links)

    assert str(exc.value) == "invalid_link_transition"
    assert not links.updated


def test_invalid_transition_does_not_write__AC10():
    link = FamilyLink(1, uuid4(), uuid4(), LinkStatus.PENDING)
    links = FakeLinks([link])

    with pytest.raises(Conflict, match="invalid_link_transition"):
        revoked(links)

    assert not links.updated


NOW = datetime(2026, 10, 7, tzinfo=UTC)


class FakeAudit:
    def __init__(self):
        self.events = []
        self.failure = None

    def allowed(self, *args):
        if self.failure:
            raise self.failure
        self.events.append(("allowed", args))

    def denied(self, *args):
        if self.failure:
            raise self.failure
        self.events.append(("denied", args))


class FakeConfirmations:
    def __init__(self):
        self.record = None
        self.inserts = 0
        self.clock_calls = 0

    def get(self, uow, link):
        return self.record

    def insert(self, uow, link, document_version):
        self.inserts += 1
        self.record = ConsentConfirmation(
            91,
            link.id,
            link.patient_user_id,
            link.family_user_id,
            "family_sharing",
            document_version,
            NOW,
        )
        return self.record

    def now(self, uow):
        self.clock_calls += 1
        return NOW


class FakeConsent:
    active = True
    current = "2026-10-v1"

    def __init__(self):
        self.checked_patients = []

    def lock_active(self, uow, patient_id):
        self.checked_patients.append(patient_id)
        return self.active

    def check_version(self, document_version):
        if document_version != self.current:
            raise DomainError("consent_document_outdated")


def context(status=LinkStatus.PENDING, **kwargs):
    link = FamilyLink(1, uuid4(), uuid4(), status, linked_at=NOW, **kwargs)
    return SimpleNamespace(
        links=FakeLinks([link]),
        confirmations=FakeConfirmations(),
        consent=FakeConsent(),
        audit=FakeAudit(),
        link=link,
    )


def approved(links, **kwargs):
    link = links.links[1]
    defaults = dict(
        link_id=1,
        actor_id=link.patient_user_id,
        is_admin=False,
        family_user_id=link.family_user_id,
        consent_confirmed=True,
        document_version="2026-10-v1",
        links=links,
        confirmations=FakeConfirmations(),
        consent=FakeConsent(),
        audit=FakeAudit(),
    )
    defaults.update(kwargs)
    return approve_link(object(), **defaults)


def rejected(links, **kwargs):
    link = links.links[1]
    defaults = dict(
        link_id=1,
        actor_id=link.patient_user_id,
        is_admin=False,
        links=links,
        confirmations=FakeConfirmations(),
        audit=FakeAudit(),
    )
    defaults.update(kwargs)
    return reject_link(object(), **defaults)


def revoked(links, **kwargs):
    link = links.links[1]
    defaults = dict(
        link_id=1,
        actor_id=link.patient_user_id,
        is_admin=False,
        links=links,
        confirmations=FakeConfirmations(),
        audit=FakeAudit(),
    )
    defaults.update(kwargs)
    return revoke_link(object(), **defaults)


class FakeNames:
    def __init__(self, records=None):
        self.records = records or {}
        self.calls = []

    def get(self, uow, ids):
        self.calls.append(ids)
        return self.records


def shared(c, enabled=True, **kwargs):
    defaults = dict(
        link_id=1,
        actor_id=c.link.patient_user_id,
        is_admin=False,
        enabled=enabled,
        links=c.links,
        confirmations=c.confirmations,
        consent=c.consent,
        names=FakeNames({c.link.family_user_id: "Nguyen An"}),
        audit=c.audit,
    )
    defaults.update(kwargs)
    return update_sharing(object(), **defaults)


def approve_context(c, **kwargs):
    return approved(
        c.links, confirmations=c.confirmations, consent=c.consent, audit=c.audit, **kwargs
    )


@pytest.mark.parametrize("operation", ["approve", "reject"])
@pytest.mark.parametrize("actor", ["family", "stranger", "admin"])
def test_only_patient_may_decide(operation, actor):
    c = context()
    actor_id = c.link.family_user_id if actor == "family" else uuid4()
    call = (
        approve_context
        if operation == "approve"
        else lambda c, **k: rejected(c.links, audit=c.audit, **k)
    )
    with pytest.raises(Forbidden, match="khong_co_quyen"):
        call(c, actor_id=actor_id, is_admin=actor == "admin")
    assert not c.links.updated and not c.confirmations.inserts
    kind, args = c.audit.events[0]
    assert kind == "denied" and args[0] == actor_id
    assert args[1:3] == ((None, None) if actor == "admin" else (c.link.patient_user_id, 1))


def test_admin_is_denied_before_link_lookup():
    c = context()
    c.links.get_for_update = lambda *args: pytest.fail("admin looked up a link")
    with pytest.raises(Forbidden):
        approve_context(c, is_admin=True)


def test_wrong_family_is_denied_before_consent():
    c = context()
    with pytest.raises(Forbidden):
        approve_context(c, family_user_id=uuid4())
    assert not c.consent.checked_patients and not c.links.updated


def test_missing_link_is_not_found_without_state_or_allowed_audit():
    c = context()
    with pytest.raises(NotFound, match="family_link_not_found"):
        approve_context(c, link_id=999)
    assert not c.audit.events


@pytest.mark.parametrize("status", [LinkStatus.PENDING, LinkStatus.ACTIVE])
def test_withdrawn_consent_blocks_pending_and_replay(status):
    c = context(status)
    c.consent.active = False
    with pytest.raises(Forbidden, match="consent_revoked"):
        approve_context(c)
    assert c.consent.checked_patients == [c.link.patient_user_id]
    assert c.audit.events[0][1][-1] == "consent_revoked"
    assert not c.links.updated and not c.confirmations.inserts


@pytest.mark.parametrize("confirmation", [False, None, 1, "true"])
def test_confirmation_must_be_explicit_boolean_true(confirmation):
    c = context()
    with pytest.raises(DomainError, match="consent_confirmation_required"):
        approve_context(c, consent_confirmed=confirmation)
    assert not c.links.updated and not c.confirmations.inserts


def test_pending_outdated_version_has_no_writes():
    c = context()
    with pytest.raises(DomainError, match="consent_document_outdated"):
        approve_context(c, document_version="old")
    assert not c.links.updated and not c.confirmations.inserts and not c.audit.events


def test_approve_stores_exact_pair_and_preserves_requested_time_and_false_sharing():
    c = context(sharing_enabled=True)
    result = approve_context(c)
    assert result.link.status is LinkStatus.ACTIVE
    assert result.link.sharing_enabled is False and result.link.linked_at == NOW
    assert result.confirmation.patient_user_id == c.link.patient_user_id
    assert result.confirmation.family_user_id == c.link.family_user_id
    assert result.confirmation.link_id == 1 and c.confirmations.inserts == 1
    assert c.audit.events[0][0] == "allowed"


def test_replay_preserves_evidence_and_current_sharing_after_version_change():
    c = context()
    first = approve_context(c)
    c.consent.current = "new-version"
    c.links.links[1] = replace(first.link, sharing_enabled=True)
    second = approve_context(c)
    assert second.confirmation == first.confirmation and c.confirmations.inserts == 1
    assert second.link.sharing_enabled is True and len(c.audit.events) == 2
    assert c.consent.checked_patients == [c.link.patient_user_id] * 2
    with pytest.raises(Conflict, match="link_approval_conflict"):
        approve_context(c, document_version="new-version")
    assert c.confirmations.inserts == 1


def test_legacy_active_missing_evidence_is_not_backfilled():
    c = context(LinkStatus.ACTIVE)
    with pytest.raises(Conflict, match="consent_confirmation_missing"):
        approve_context(c)
    assert not c.confirmations.inserts and not c.links.updated


def test_reject_needs_no_consent_preserves_time_and_replays_once():
    c = context(sharing_enabled=True)
    first = rejected(c.links, confirmations=c.confirmations, audit=c.audit)
    second = rejected(c.links, confirmations=c.confirmations, audit=c.audit)
    assert first == second and first.rejected_at == NOW
    assert first.linked_at == NOW and first.sharing_enabled is False
    assert c.confirmations.clock_calls == 1 and not c.confirmations.inserts
    assert len(c.audit.events) == 2 and len(c.links.updated) == 1


@pytest.mark.parametrize("status", [LinkStatus.ACTIVE, LinkStatus.REVOKED])
def test_reject_active_or_revoked_conflicts_without_writes(status):
    c = context(status)
    with pytest.raises(Conflict, match="invalid_link_transition"):
        rejected(c.links, audit=c.audit)
    assert not c.links.updated and not c.audit.events


def test_durable_audit_failure_propagates_instead_of_success():
    c = context()
    c.audit.failure = RuntimeError("audit unavailable")
    with pytest.raises(RuntimeError, match="audit unavailable"):
        approve_context(c)
    with pytest.raises(RuntimeError, match="audit unavailable"):
        rejected(c.links, actor_id=uuid4(), audit=c.audit)


def test_evidence_insert_failure_prevents_status_update_and_allowed_audit():
    c = context()

    def failed(*args):
        raise RuntimeError("evidence unavailable")

    c.confirmations.insert = failed
    with pytest.raises(RuntimeError, match="evidence unavailable"):
        approve_context(c)
    assert not c.links.updated and not c.audit.events


# --- adhoc-20261020-family-link-approval: bật/tắt chia sẻ, hủy liên kết ---------------------


def active_context(sharing=False, evidence=True):
    c = context(LinkStatus.ACTIVE, sharing_enabled=sharing)
    if evidence:
        c.confirmations.record = ConsentConfirmation(
            91, 1, c.link.patient_user_id, c.link.family_user_id, "family_sharing", "v1", NOW
        )
    return c


@pytest.mark.parametrize("enabled", [True, False])
def test_update_sharing_sets_value_audits_and_returns_caregiver__AC12(enabled):
    c = active_context(sharing=not enabled)

    result = shared(c, enabled)

    assert c.links.links[1].sharing_enabled is enabled
    assert (result.link_id, result.family_user_id) == (1, c.link.family_user_id)
    assert (result.family_full_name, result.sharing_enabled, result.approved_at) == (
        "Nguyen An",
        enabled,
        NOW,
    )
    operation = "enable_sharing" if enabled else "disable_sharing"
    assert c.audit.events == [
        (
            "allowed",
            (c.audit.events[0][1][0], c.link.patient_user_id, c.link.patient_user_id, 1, operation),
        )
    ]


@pytest.mark.parametrize("enabled", [True, False])
def test_update_sharing_same_value_writes_nothing_but_audits__AC12(enabled):
    c = active_context(sharing=enabled)

    result = shared(c, enabled)

    assert result.sharing_enabled is enabled
    assert not c.links.updated
    assert [kind for kind, _ in c.audit.events] == ["allowed"]


@pytest.mark.parametrize("enabled", [True, False])
@pytest.mark.parametrize("actor", ["family", "stranger", "admin"])
def test_only_patient_may_change_sharing__AC5(enabled, actor):
    c = active_context()
    actor_id = c.link.family_user_id if actor == "family" else uuid4()

    with pytest.raises(Forbidden, match="khong_co_quyen"):
        shared(c, enabled, actor_id=actor_id, is_admin=actor == "admin")

    assert not c.links.updated
    kind, args = c.audit.events[0]
    assert kind == "denied" and args[0] == actor_id
    assert args[1:3] == ((None, None) if actor == "admin" else (c.link.patient_user_id, 1))
    assert args[3] == ("enable_sharing" if enabled else "disable_sharing")


def test_update_sharing_missing_link_is_not_found__AC10():
    c = active_context()
    with pytest.raises(NotFound, match="family_link_not_found"):
        shared(c, link_id=999)
    assert not c.audit.events


@pytest.mark.parametrize("status", [LinkStatus.PENDING, LinkStatus.REJECTED, LinkStatus.REVOKED])
@pytest.mark.parametrize("enabled", [True, False])
def test_update_sharing_on_non_active_conflicts_before_consent__AC10(status, enabled):
    c = context(status)
    with pytest.raises(Conflict, match="family_link_not_active"):
        shared(c, enabled)
    assert not c.consent.checked_patients and not c.links.updated and not c.audit.events


def test_enable_without_consent_is_denied_with_reason__AC7_AC10():
    c = active_context()
    c.consent.active = False

    with pytest.raises(Forbidden, match="consent_revoked"):
        shared(c, True)

    assert not c.links.updated
    kind, args = c.audit.events[0]
    assert kind == "denied" and args[1:] == (
        c.link.patient_user_id,
        1,
        "enable_sharing",
        "consent_revoked",
    )


def test_enable_checks_consent_even_when_already_enabled__AC10():
    c = active_context(sharing=True)
    c.consent.active = False
    with pytest.raises(Forbidden, match="consent_revoked"):
        shared(c, True)


def test_disable_needs_no_consent__AC12():
    c = active_context(sharing=True)
    c.consent.active = False

    assert shared(c, False).sharing_enabled is False
    assert not c.consent.checked_patients


def test_enable_legacy_link_without_evidence_conflicts__AC10():
    c = active_context(evidence=False)
    with pytest.raises(Conflict, match="consent_confirmation_missing"):
        shared(c, True)
    assert not c.links.updated and not c.audit.events


def test_disable_legacy_link_without_evidence_is_allowed__AC12():
    c = active_context(sharing=True, evidence=False)
    result = shared(c, False)
    assert result.sharing_enabled is False and result.approved_at is None


def test_update_sharing_audit_failure_propagates__AC12():
    c = active_context()
    c.audit.failure = RuntimeError("audit unavailable")
    with pytest.raises(RuntimeError, match="audit unavailable"):
        shared(c, True)


@pytest.mark.parametrize("actor", ["family", "stranger", "admin"])
def test_only_patient_may_revoke__AC5(actor):
    c = active_context(sharing=True)
    actor_id = c.link.family_user_id if actor == "family" else uuid4()

    with pytest.raises(Forbidden, match="khong_co_quyen"):
        revoked(c.links, actor_id=actor_id, is_admin=actor == "admin", audit=c.audit)

    assert not c.links.updated
    kind, args = c.audit.events[0]
    assert kind == "denied" and args[0] == actor_id and args[3] == "revoke"


def test_revoke_admin_denied_before_link_lookup__AC5():
    c = active_context()
    c.links.get_for_update = lambda *args: pytest.fail("admin looked up a link")
    with pytest.raises(Forbidden):
        revoked(c.links, actor_id=uuid4(), is_admin=True, audit=c.audit)


def test_revoke_uses_db_clock_keeps_request_time_and_audits__AC13():
    c = active_context(sharing=True)

    result = revoked(c.links, confirmations=c.confirmations, audit=c.audit)

    assert result.status is LinkStatus.REVOKED and result.revoked_at == NOW
    assert result.linked_at == NOW and c.confirmations.clock_calls == 1
    assert not c.confirmations.inserts
    kind, args = c.audit.events[0]
    assert kind == "allowed" and args[1:] == (
        c.link.patient_user_id,
        c.link.patient_user_id,
        1,
        "revoke",
    )


def test_revoke_replay_returns_first_result_without_writes__AC13():
    c = active_context()
    first = revoked(c.links, confirmations=c.confirmations, audit=c.audit)
    second = revoked(c.links, confirmations=c.confirmations, audit=c.audit)

    assert first == second and c.confirmations.clock_calls == 1
    assert len(c.links.updated) == 1 and len(c.audit.events) == 2


@pytest.mark.parametrize("status", [LinkStatus.PENDING, LinkStatus.REJECTED])
def test_revoke_pending_or_rejected_conflicts_without_writes__AC10(status):
    c = context(status)
    with pytest.raises(Conflict, match="invalid_link_transition"):
        revoked(c.links, audit=c.audit)
    assert not c.links.updated and not c.audit.events


def test_revoke_missing_link_is_not_found__AC10():
    c = active_context()
    with pytest.raises(NotFound, match="family_link_not_found"):
        revoked(c.links, link_id=999, audit=c.audit)
