from unittest.mock import Mock, patch
from uuid import uuid4

import pytest

from drugtime.modules.medication.adapters.outbound.other_modules import AccessGuardAdapter
from drugtime.modules.medication.application.list_linked_patient_medications import (
    list_linked_patient_medications,
)
from drugtime.modules.medication.domain import patient_medication_cursor as cursor
from drugtime.shared.errors import DomainError, Forbidden


def test_patient_medication_adapter_audits_self():
    patient = uuid4()
    with patch(
        "drugtime.modules.medication.adapters.outbound.other_modules.access.authorize"
    ) as pep:
        AccessGuardAdapter(audit_self=True).authorize_read(None, patient, False, patient)
    assert pep.call_args.kwargs["audit_self"] is True


def test_existing_medication_adapter_keeps_default_audit():
    patient = uuid4()
    with patch(
        "drugtime.modules.medication.adapters.outbound.other_modules.access.authorize"
    ) as pep:
        AccessGuardAdapter().authorize_read(None, patient, False, patient)
    assert pep.call_args.kwargs["audit_self"] is False


def test_cursor_bound_to_patient_filter_and_int64():
    patient = uuid4()
    assert (
        cursor.decode(cursor.encode(patient, 9223372036854775807), patient) == 9223372036854775807
    )
    for value in [
        "!",
        cursor.encode(uuid4(), 5),
        cursor.encode(patient, 0),
        cursor.encode(patient, True),
        cursor.encode(patient, 9223372036854775808),
    ]:
        with pytest.raises(DomainError, match="invalid_cursor"):
            cursor.decode(value, patient)


def test_pep_precedes_decode_and_any_health_read():
    guard, meds = Mock(), Mock()
    guard.authorize_read.side_effect = Forbidden("khong_co_quyen")
    with pytest.raises(Forbidden):
        list_linked_patient_medications(
            None,
            caller_id=uuid4(),
            caller_is_admin=False,
            patient_id=uuid4(),
            limit=2,
            cursor="broken",
            access=guard,
            catalog=Mock(),
            meds=meds,
        )
    meds.active_ids_page.assert_not_called()


def test_descending_page_includes_records_without_schedules():
    patient, meds = uuid4(), Mock()
    meds.active_ids_page.return_value = [9, 5, 2]
    with patch(
        "drugtime.modules.medication.application.list_linked_patient_medications.load_view",
        side_effect=lambda u, mid, m, c: mid,
    ):
        result = list_linked_patient_medications(
            None,
            caller_id=uuid4(),
            caller_is_admin=False,
            patient_id=patient,
            limit=2,
            cursor=None,
            access=Mock(),
            catalog=Mock(),
            meds=meds,
        )
    assert result.items == [9, 5]
    assert cursor.decode(result.next_cursor, patient) == 5
    meds.active_ids_page.assert_called_once_with(None, patient, None, 3)


def test_empty_page_has_no_cursor():
    meds = Mock()
    meds.active_ids_page.return_value = []
    result = list_linked_patient_medications(
        None,
        caller_id=uuid4(),
        caller_is_admin=False,
        patient_id=uuid4(),
        limit=100,
        cursor=None,
        access=Mock(),
        catalog=Mock(),
        meds=meds,
    )
    assert result.items == [] and result.next_cursor is None
