from dataclasses import replace
from types import SimpleNamespace
from uuid import uuid4

import pytest

from drugtime.modules.family.application.list_caregivers import list_caregivers
from drugtime.modules.family.domain.link import FamilyLink, LinkStatus
from drugtime.shared.errors import Forbidden
from tests.unit.test_family_manage_links import NOW, FakeAudit
from tests.unit.test_family_pending_links import Names


def _active(patient, sharing=False):
    return FamilyLink(uuid4().int % 1000 + 1, patient, uuid4(), LinkStatus.ACTIVE, sharing)


def test_list_uses_session_patient_batch_names_and_minimal_projection__AC11():
    patient = uuid4()
    first, legacy = _active(patient, sharing=True), _active(patient)
    seen = []
    links = SimpleNamespace(
        list_caregivers=lambda uow, actor: seen.append(actor) or [(first, NOW), (legacy, None)]
    )
    names = Names({first.family_user_id: "Nguyen An"})
    audit = FakeAudit()

    result = list_caregivers(
        object(), actor_id=patient, is_admin=False, links=links, names=names, audit=audit
    )

    assert seen == [patient]
    assert len(names.calls) == 1
    assert set(names.calls[0]) == {first.family_user_id, legacy.family_user_id}
    assert [(r.link_id, r.family_full_name, r.sharing_enabled, r.approved_at) for r in result] == [
        (first.id, "Nguyen An", True, NOW),
        (legacy.id, None, False, None),
    ]
    assert set(vars(result[0])) == {
        "link_id",
        "family_user_id",
        "family_full_name",
        "sharing_enabled",
        "approved_at",
    }
    assert len(audit.events) == 1 and audit.events[0][0] == "allowed"
    assert audit.events[0][1][1:] == (patient, patient, None, "list_caregivers")


def test_empty_list_still_audited__AC11():
    audit = FakeAudit()
    links = SimpleNamespace(list_caregivers=lambda uow, actor: [])

    assert (
        list_caregivers(
            object(), actor_id=uuid4(), is_admin=False, links=links, names=Names({}), audit=audit
        )
        == []
    )
    assert audit.events[0][0] == "allowed" and audit.events[0][1][-1] == "list_caregivers"


def test_admin_denied_before_reading_links__AC5():
    audit = FakeAudit()
    admin = uuid4()

    with pytest.raises(Forbidden, match="khong_co_quyen"):
        list_caregivers(
            object(), actor_id=admin, is_admin=True, links=None, names=None, audit=audit
        )

    kind, args = audit.events[0]
    assert kind == "denied" and args == (admin, None, None, "list_caregivers", "khong_co_quyen")


def test_list_does_not_return_items_when_audit_fails__AC11():
    audit = FakeAudit()
    audit.failure = RuntimeError("audit unavailable")
    link = replace(_active(uuid4()), sharing_enabled=True)

    with pytest.raises(RuntimeError, match="audit unavailable"):
        list_caregivers(
            object(),
            actor_id=link.patient_user_id,
            is_admin=False,
            links=SimpleNamespace(list_caregivers=lambda *args: [(link, NOW)]),
            names=Names({}),
            audit=audit,
        )
