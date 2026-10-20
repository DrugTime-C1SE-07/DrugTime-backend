from dataclasses import replace
from types import SimpleNamespace
from uuid import uuid4

import pytest

from drugtime.modules.family.application.list_pending_links import list_pending_links
from drugtime.shared.errors import Forbidden
from tests.unit.test_family_manage_links import NOW, FakeAudit, context


class Names:
    def __init__(self, records):
        self.records = records
        self.calls = []

    def get(self, uow, ids):
        self.calls.append(ids)
        return self.records


def test_list_uses_session_patient_batch_names_and_minimal_projection_without_consent():
    c = context()
    second = replace(c.link, id=2, family_user_id=uuid4())
    links = SimpleNamespace(list_pending=lambda uow, patient: [c.link, second])
    names = Names({c.link.family_user_id: "Nguyen An"})
    result = list_pending_links(
        object(),
        actor_id=c.link.patient_user_id,
        is_admin=False,
        links=links,
        names=names,
        audit=c.audit,
    )
    assert len(names.calls) == 1 and set(names.calls[0]) == {
        c.link.family_user_id,
        second.family_user_id,
    }
    assert [(r.link_id, r.family_full_name, r.requested_at) for r in result] == [
        (1, "Nguyen An", NOW),
        (2, None, NOW),
    ]
    assert set(vars(result[0])) == {"link_id", "family_user_id", "family_full_name", "requested_at"}
    assert c.audit.events[0][0] == "allowed"
    assert c.audit.events[0][1][1:] == (
        c.link.patient_user_id,
        c.link.patient_user_id,
        None,
        "list_pending",
    )


def test_empty_list_still_audited_and_no_cutoff():
    audit, names = FakeAudit(), Names({})
    patient = uuid4()
    seen = []
    links = SimpleNamespace(list_pending=lambda uow, actor: seen.append(actor) or [])
    assert (
        list_pending_links(
            object(), actor_id=patient, is_admin=False, links=links, names=names, audit=audit
        )
        == []
    )
    assert seen == [patient] and audit.events[0][0] == "allowed"


def test_list_admin_denied_before_reading_names_or_links():
    audit = FakeAudit()
    with pytest.raises(Forbidden, match="khong_co_quyen"):
        list_pending_links(
            object(), actor_id=uuid4(), is_admin=True, links=None, names=None, audit=audit
        )
    assert audit.events[0][0] == "denied" and audit.events[0][1][1:3] == (None, None)


def test_list_does_not_return_items_when_audit_fails():
    audit = FakeAudit()
    audit.failure = RuntimeError("audit unavailable")
    with pytest.raises(RuntimeError, match="audit unavailable"):
        list_pending_links(
            object(),
            actor_id=uuid4(),
            is_admin=False,
            links=SimpleNamespace(list_pending=lambda *args: []),
            names=Names({}),
            audit=audit,
        )
