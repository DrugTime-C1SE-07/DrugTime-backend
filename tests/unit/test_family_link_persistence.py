from contextlib import contextmanager
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy.exc import SQLAlchemyError

from drugtime.modules.family.adapters.outbound import sql_link_audit
from drugtime.modules.family.adapters.outbound.sql_confirmations import SqlConfirmations
from tests.unit.test_family_manage_links import NOW, context


class Connection:
    def __init__(self, row=None, failure=None):
        self.row, self.failure, self.calls = row, failure, []

    def execute(self, sql, params=None):
        self.calls.append((str(sql), params))
        if self.failure:
            raise self.failure
        return SimpleNamespace(first=lambda: self.row, one=lambda: self.row, scalar_one=lambda: NOW)


def test_confirmation_insert_and_lookup_use_exact_pair_and_database_time():
    link = context().link
    values = dict(
        id=91,
        link_id=1,
        patient_user_id=link.patient_user_id,
        family_user_id=link.family_user_id,
        purpose="family_sharing",
        document_version="v1",
        confirmed_at=NOW,
    )
    c = Connection(SimpleNamespace(_mapping=values))
    uow, adapter = SimpleNamespace(connection=c), SqlConfirmations()
    saved = adapter.insert(uow, link, "v1")
    assert saved == adapter.get(uow, link) and saved.confirmed_at == NOW
    assert c.calls[0][1] == {"l": 1, "p": link.patient_user_id, "f": link.family_user_id, "v": "v1"}
    assert "confirmed_at) VALUES" not in c.calls[0][0]  # timestamp from DB/trigger
    assert c.calls[1][1] == {"l": 1, "p": link.patient_user_id, "f": link.family_user_id}
    assert "patient_user_id = :p AND family_user_id = :f" in c.calls[1][0]
    assert adapter.now(uow) == NOW and "clock_timestamp()" in c.calls[-1][0]


def test_missing_confirmation_returns_none():
    assert SqlConfirmations().get(SimpleNamespace(connection=Connection()), context().link) is None


def test_allowed_audit_uses_main_uow_and_denied_commits_separate_uow(monkeypatch):
    main, own, events = Connection(), Connection(), []

    @contextmanager
    def separate():
        events.append("begin")
        yield SimpleNamespace(connection=own)
        events.append("commit")

    monkeypatch.setattr(sql_link_audit, "unit_of_work", separate)
    actor, patient = uuid4(), uuid4()
    audit = sql_link_audit.SqlLinkAudit()
    audit.allowed(SimpleNamespace(connection=main), actor, patient, 7, "approve")
    assert not events
    audit.denied(actor, patient, 7, "reject", "khong_co_quyen")
    assert events == ["begin", "commit"]
    assert main.calls[0][1] == {
        "a": actor,
        "p": patient,
        "l": 7,
        "op": "approve",
        "result": "allowed",
        "reason": None,
    }
    assert own.calls[0][1]["result"] == "denied"
    assert set(own.calls[0][1]) == {"a", "p", "l", "op", "result", "reason"}


def test_denied_audit_commit_failure_is_not_swallowed(monkeypatch):
    @contextmanager
    def broken():
        yield SimpleNamespace(connection=Connection())
        raise SQLAlchemyError("commit failed")

    monkeypatch.setattr(sql_link_audit, "unit_of_work", broken)
    with pytest.raises(SQLAlchemyError):
        sql_link_audit.SqlLinkAudit().denied(uuid4(), None, None, "approve", "khong_co_quyen")
