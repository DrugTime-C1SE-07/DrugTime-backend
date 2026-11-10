from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

from drugtime.modules.family import api as family
from drugtime.modules.family.adapters.outbound import sql_link_audit


def test_family_candidate_facade_uses_caller_id(monkeypatch):
    caller, patient, uow = uuid4(), uuid4(), object()
    links = Mock()
    links.sharing_patient_ids.return_value = [patient]
    monkeypatch.setattr(family, "SqlLinks", lambda: links)
    assert family.sharing_patient_ids(uow, caller) == [patient]
    links.sharing_patient_ids.assert_called_once_with(uow, caller)


def test_request_audit_uses_null_subject_and_existing_writer(monkeypatch):
    audit, caller, uow = Mock(), uuid4(), object()
    monkeypatch.setattr(family, "SqlLinkAudit", lambda: audit)
    family.audit_empty_patient_list(uow, caller)
    family.audit_denied_patient_list(caller)
    audit.allowed.assert_called_once_with(uow, caller, None, None, "list_linked_patients")
    audit.denied.assert_called_once_with(
        caller, None, None, "list_linked_patients", "khong_co_quyen"
    )


def test_denied_writer_uses_independent_transaction(monkeypatch):
    events, connection = [], Mock()

    @contextmanager
    def own():
        events.append("begin")
        yield SimpleNamespace(connection=connection)
        events.append("commit")

    monkeypatch.setattr(sql_link_audit, "unit_of_work", own)
    caller = uuid4()
    sql_link_audit.SqlLinkAudit().denied(
        caller, None, None, "list_linked_patients", "khong_co_quyen"
    )
    assert events == ["begin", "commit"]
    params = connection.execute.call_args.args[1]
    assert params == {
        "a": caller,
        "p": None,
        "l": None,
        "op": "list_linked_patients",
        "result": "denied",
        "reason": "khong_co_quyen",
    }


def test_family_gateway_calls_public_api_only(monkeypatch):
    from drugtime.modules.access.adapters.outbound import linked_patients_gateway as gateway

    uow, caller, patient = object(), uuid4(), uuid4()
    ids, names, empty, denied = (
        Mock(return_value=[patient]),
        Mock(return_value={patient: None}),
        Mock(),
        Mock(),
    )
    monkeypatch.setattr(gateway.family, "sharing_patient_ids", ids)
    monkeypatch.setattr(gateway.identity, "display_names", names)
    monkeypatch.setattr(gateway.family, "audit_empty_patient_list", empty)
    monkeypatch.setattr(gateway.family, "audit_denied_patient_list", denied)
    assert gateway.LinkedPatientCandidates().ids(uow, caller) == [patient]
    assert gateway.LinkedPatientNames().get(uow, [patient]) == {patient: None}
    audit = gateway.LinkedPatientRequestAudit()
    audit.empty(uow, caller)
    audit.denied(caller)
    ids.assert_called_once_with(uow, caller)
    names.assert_called_once_with(uow, [patient])
    empty.assert_called_once_with(uow, caller)
    denied.assert_called_once_with(caller)
