from datetime import datetime, time
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql

from drugtime.modules.adherence.adapters.outbound.sql_adherence import SqlAdherenceHistory
from drugtime.modules.adherence.application.get_adherence_history import get_adherence_history
from drugtime.modules.adherence.domain.dose import DoseStatus
from drugtime.modules.adherence.domain.history import VIETNAM, GroupBy, HistoryRange, HistoryRow
from drugtime.shared.errors import Forbidden

NOW = datetime(2026, 10, 19, 12, tzinfo=VIETNAM)
PATIENT, CALLER = uuid4(), uuid4()
PERIOD = HistoryRange(NOW.date(), NOW.date())


def test_sql_reader_maps_raw_logs_with_one_read_only_statement():
    scheduled = NOW.replace(hour=10, microsecond=123456)
    rows = [
        SimpleNamespace(
            medication_id=1,
            medication_name="Medicine",
            schedule_id=7,
            scheduled_at=scheduled,
            taken_at=None,
            status=status,
        )
        for status in (None, "bo_lo")
    ]
    connection = Mock(execute=Mock(return_value=iter(rows)))
    result = SqlAdherenceHistory().read(
        SimpleNamespace(connection=connection), PATIENT, PERIOD, NOW
    )
    assert [r.status for r in result] == [None, DoseStatus.MISSED]
    assert all(r.scheduled_at == scheduled and r.taken_at is None for r in result)
    connection.execute.assert_called_once()
    statement, params = connection.execute.call_args.args
    compiled = str(statement.compile(dialect=postgresql.dialect())).upper()
    assert not any(word in compiled for word in ("INSERT ", "UPDATE ", "DELETE "))
    assert params == dict(
        patient_id=PATIENT,
        from_date=NOW.date(),
        to_date=NOW.date(),
        timezone="Asia/Ho_Chi_Minh",
        as_of=NOW,
        start_at=datetime.combine(NOW.date(), time.min, VIETNAM),
        end_at=datetime(2026, 10, 20, tzinfo=VIETNAM),
    )


def test_sql_reader_does_not_substitute_empty_history_on_database_failure():
    connection = Mock(execute=Mock(side_effect=RuntimeError("database unavailable")))
    with pytest.raises(RuntimeError, match="database unavailable"):
        SqlAdherenceHistory().read(SimpleNamespace(connection=connection), PATIENT, PERIOD, NOW)


def call(access, reader, **kw):
    return get_adherence_history(
        object(),
        **dict(
            caller_id=CALLER,
            caller_is_admin=False,
            patient_id=PATIENT,
            start=None,
            end=None,
            group_by=GroupBy.DATE,
            as_of=NOW,
            access=access,
            reader=reader,
            **kw,
        ),
    )


@pytest.mark.parametrize("patient", [PATIENT, None])
def test_authorization_runs_before_reader_and_resolved_patient_single_as_of_forwarded(patient):
    events = []
    access = Mock(authorize_history=Mock(side_effect=lambda *args: events.append("authorize")))
    reader = Mock(read=Mock(side_effect=lambda *args: events.append("read") or []))
    result = get_adherence_history(
        object(),
        caller_id=CALLER,
        caller_is_admin=True,
        patient_id=patient,
        start=None,
        end=None,
        group_by=GroupBy.DATE,
        as_of=NOW,
        access=access,
        reader=reader,
    )
    assert events == ["authorize", "read"]
    target = patient or CALLER
    assert access.authorize_history.call_args.args[1:] == (CALLER, True, target)
    assert reader.read.call_args.args[1:] == (
        target,
        HistoryRange(datetime(2026, 9, 20).date(), NOW.date()),
        NOW,
    )
    assert result.patient_id == target and result.as_of == NOW


@pytest.mark.parametrize("error", [Forbidden("khong_co_quyen"), RuntimeError("audit failure")])
def test_denied_or_audit_failure_never_reads_history(error):
    access = Mock(authorize_history=Mock(side_effect=error))
    reader = Mock()
    with pytest.raises(type(error)):
        call(access, reader)
    reader.read.assert_not_called()


def test_single_materialized_rows_feed_all_groups_and_early_missed_is_normalized():
    rows = iter(
        [
            HistoryRow(
                1, "Medicine", 1, NOW.replace(hour=9), NOW.replace(hour=9), DoseStatus.TAKEN
            ),
            HistoryRow(1, "Medicine", 2, NOW.replace(hour=10), None, DoseStatus.MISSED),
            HistoryRow(2, "Other", 3, NOW.replace(hour=8), None, None),
        ]
    )
    reader = Mock(read=Mock(return_value=rows))
    result = call(Mock(), reader)
    reader.read.assert_called_once()
    assert result.summary.total == sum(g.summary.total for g in result.groups) == 3
    assert (result.summary.taken, result.summary.pending, result.summary.missed) == (1, 1, 1)
    assert result.summary.adherence_rate == 50
    assert result.groups[0].doses[-1].status_source == "inferred"


def test_reader_failure_is_not_empty_success():
    with pytest.raises(RuntimeError):
        call(Mock(), Mock(read=Mock(side_effect=RuntimeError("read failed"))))


def test_no_authorization_cache():
    access, reader = Mock(), Mock(read=Mock(return_value=[]))
    call(access, reader)
    access.authorize_history.side_effect = Forbidden("consent_revoked")
    with pytest.raises(Forbidden, match="consent_revoked"):
        call(access, reader)
    assert access.authorize_history.call_count == 2
    assert reader.read.call_count == 1
