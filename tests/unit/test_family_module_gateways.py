from types import SimpleNamespace
from uuid import uuid4

import pytest

from drugtime.modules.consent import api as consent
from drugtime.modules.consent.adapters.outbound.sql_consent import SqlConsents
from drugtime.modules.family.adapters.outbound import module_gateways as gateways
from drugtime.shared.errors import DomainError


@pytest.mark.parametrize("active", [False, True])
def test_gateway_reads_locked_patient_consent_each_time(monkeypatch, active):
    patient, uow, calls = uuid4(), object(), []
    monkeypatch.setattr(
        gateways.consent, "lock_active_consent", lambda *args: calls.append(args) or active
    )
    gateway = gateways.SharingConsentGateway()
    assert gateway.lock_active(uow, patient) is active
    assert gateway.lock_active(uow, patient) is active
    assert calls == [(uow, patient, consent.Purpose.FAMILY_SHARING)] * 2


def test_gateway_version_uses_public_consent_rules():
    gateway = gateways.SharingConsentGateway()
    gateway.check_version("2026-10-v1")
    with pytest.raises(DomainError, match="consent_document_outdated"):
        gateway.check_version("old")


def test_gateway_names_use_public_batch_projection(monkeypatch):
    ids, uow = [uuid4()], object()
    calls = []
    monkeypatch.setattr(gateways.identity, "display_names", lambda *args: calls.append(args) or {})
    assert gateways.DisplayNamesGateway().get(uow, ids) == {} and calls == [(uow, ids)]


@pytest.mark.parametrize("present", [None, object()])
def test_consent_query_locks_effective_row_for_share(present):
    calls = []
    connection = SimpleNamespace(
        execute=lambda sql, params: (
            calls.append((str(sql), params)) or SimpleNamespace(first=lambda: present)
        )
    )
    patient = uuid4()
    assert SqlConsents().lock_active(
        SimpleNamespace(connection=connection), patient, "family_sharing"
    ) is (present is not None)
    sql, params = calls[0]
    assert "FOR SHARE" in sql and "status = 'dong_y'" in sql
    assert params == {"u": patient, "p": "family_sharing"}


def test_public_consent_lock_delegates_to_store(monkeypatch):
    calls = []
    monkeypatch.setattr(
        consent.SqlConsents, "lock_active", lambda self, *args: calls.append(args) or True
    )
    uow, patient = object(), uuid4()
    assert consent.lock_active_consent(uow, patient, consent.Purpose.FAMILY_SHARING)
    assert calls == [(uow, patient, "family_sharing")]


@pytest.mark.parametrize("operation", ["approve", "reject"])
def test_public_family_api_requires_caller_and_wires_enforcement(monkeypatch, operation):
    from drugtime.modules.family import api as family

    calls = []
    method = family.approve_link if operation == "approve" else family.reject_link
    monkeypatch.setattr(
        family.manage_links,
        operation + "_link",
        lambda *args, **kwargs: calls.append((args, kwargs)) or "result",
    )
    uow, patient = object(), uuid4()
    with pytest.raises(TypeError):
        method(uow, link_id=1)
    kwargs = {"link_id": 1, "actor_id": patient, "is_admin": False}
    if operation == "approve":
        kwargs.update(family_user_id=uuid4(), consent_confirmed=True, document_version="v1")
    assert method(uow, **kwargs) == "result"
    assert calls[0][0] == (uow,) and calls[0][1]["actor_id"] == patient
    assert calls[0][1]["audit"] is not None and calls[0][1]["confirmations"] is not None
    if operation == "approve":
        assert calls[0][1]["consent"] is not None
