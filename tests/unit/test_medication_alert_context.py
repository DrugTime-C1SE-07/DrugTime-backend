from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest

from drugtime.modules.medication import api


@pytest.mark.parametrize("medication_id,name", [(None, None), (7, None), (7, "Source medicine")])
def test_context_checks_owner_then_uses_catalog_public_adapter(monkeypatch, medication_id, name):
    uow, patient = object(), uuid4()
    repo = Mock(alert_medication_id=Mock(return_value=medication_id))
    catalog = Mock(
        get_medication=Mock(return_value=None if name is None else SimpleNamespace(name=name))
    )
    monkeypatch.setattr(api, "SqlMedication", lambda: repo)
    monkeypatch.setattr(api, "CatalogAdapter", lambda: catalog)
    assert api.alert_context(uow, 15, patient) == name
    repo.alert_medication_id.assert_called_once_with(uow, 15, patient)
    if medication_id is None:
        catalog.get_medication.assert_not_called()
    else:
        catalog.get_medication.assert_called_once_with(uow, 7, include_deleted=True)


def test_context_sql_uses_only_owned_tables_and_patient_predicate():
    from drugtime.modules.medication.adapters.outbound.sql_medication import SqlMedication

    uow = Mock()
    uow.connection.execute.return_value.first.return_value = SimpleNamespace(medication_id=42)
    patient = uuid4()
    assert SqlMedication().alert_medication_id(uow, 3, patient) == 42
    query, params = uow.connection.execute.call_args.args
    assert "JOIN medications " not in str(query)
    assert "um.user_id = :p" in str(query)
    assert params == {"s": 3, "p": patient}
