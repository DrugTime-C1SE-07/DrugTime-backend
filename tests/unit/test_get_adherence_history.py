from datetime import datetime, time, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql

from drugtime.modules.adherence.adapters.outbound.sql_adherence import SqlAdherenceHistory
from drugtime.modules.adherence.application.get_adherence_history import get_adherence_history
from drugtime.modules.adherence.domain.dose import (
    DoseConfirmation,
    DoseStatus,
    status_for_confirmation,
)
from drugtime.modules.adherence.domain.history import (
    VIETNAM,
    GroupBy,
    HistoryRange,
    HistoryRow,
    Summary,
)
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


def history_snapshot(rows, as_of, group_by):
    """Use the application entry point with one fixed clock and an authorized family caller."""
    return get_adherence_history(
        object(),
        caller_id=CALLER,
        caller_is_admin=False,
        patient_id=PATIENT,
        start=as_of.date(),
        end=as_of.date(),
        group_by=group_by,
        as_of=as_of,
        access=Mock(),
        reader=Mock(read=Mock(return_value=rows)),
    )


@pytest.mark.parametrize("group_by", list(GroupBy))
@pytest.mark.parametrize(
    "delay,status,counts",
    [
        (timedelta(minutes=-30), DoseStatus.TAKEN, (1, 0)),
        (timedelta(0), DoseStatus.TAKEN, (1, 0)),
        (timedelta(minutes=30), DoseStatus.TAKEN, (1, 0)),
        (timedelta(minutes=30, microseconds=1), DoseStatus.LATE, (0, 1)),
        (timedelta(minutes=119, seconds=59), DoseStatus.LATE, (0, 1)),
        (timedelta(minutes=120), DoseStatus.LATE, (0, 1)),
    ],
)
def test_confirmed_before_deadline_counts_immediately__AC3(group_by, delay, status, counts):
    # 3.25 requirement AC3: confirmed doses count before the 120-minute deadline.
    scheduled = NOW.replace(hour=8)
    taken = scheduled + delay
    result = history_snapshot(
        [HistoryRow(1, "Medicine", 1, scheduled, taken, status)], taken, group_by
    )
    expected = Summary(1, *counts, 0, 0, 1, Decimal("100.00"))
    assert result.patient_id == PATIENT
    assert result.summary == expected
    assert len(result.groups) == 1
    assert result.groups[0].summary == expected
    (dose,) = result.groups[0].doses
    assert (dose.status, dose.status_source, dose.taken_at) == (status.value, "recorded", taken)


@pytest.mark.parametrize("group_by", list(GroupBy))
@pytest.mark.parametrize("stored_status", [None, DoseStatus.MISSED])
def test_unconfirmed_pending_at_deadline_then_missed__AC3(group_by, stored_status):
    scheduled = NOW.replace(hour=8)
    rows = [
        HistoryRow(1, "Medicine", 1, scheduled, scheduled, DoseStatus.TAKEN),
        HistoryRow(1, "Medicine", 2, scheduled, None, stored_status),
    ]
    deadline = scheduled + timedelta(minutes=120)
    at_deadline = history_snapshot(rows, deadline, group_by)
    after_deadline = history_snapshot(rows, deadline + timedelta(microseconds=1), group_by)
    for result, expected, status in (
        (at_deadline, Summary(2, 1, 0, 0, 1, 1, Decimal("100.00")), "cho_xac_nhan"),
        (after_deadline, Summary(2, 1, 0, 1, 0, 2, Decimal("50.00")), "bo_lo"),
    ):
        assert result.summary == result.groups[0].summary == expected
        doses = result.groups[0].doses
        assert [dose.schedule_id for dose in doses] == [1, 2]
        assert doses[1].status == status


@pytest.mark.parametrize("group_by", list(GroupBy))
@pytest.mark.parametrize("has_pending", [False, True])
def test_no_eligible_dose_has_null_rate__AC3(group_by, has_pending):
    scheduled = NOW.replace(hour=8)
    rows = [HistoryRow(1, "Medicine", 1, scheduled, None, None)] if has_pending else []
    result = history_snapshot(rows, scheduled + timedelta(minutes=120), group_by)
    assert result.summary == Summary(int(has_pending), 0, 0, 0, int(has_pending), 0, None)
    if has_pending:
        assert result.groups[0].summary == result.summary
        assert result.groups[0].doses[0].status == "cho_xac_nhan"
    else:
        assert result.groups == ()


@pytest.mark.parametrize("group_by", list(GroupBy))
def test_after_deadline_confirmation_does_not_raise_rate__AC3(group_by):
    scheduled = NOW.replace(hour=8)
    action_at = scheduled + timedelta(minutes=120, microseconds=1)
    confirmation = DoseConfirmation(uuid4(), 1, scheduled, action_at)
    status = status_for_confirmation(confirmation, action_at)
    assert status is DoseStatus.MISSED  # QD-10: actually taken after the deadline.
    before = history_snapshot(
        [HistoryRow(1, "Medicine", 1, scheduled, None, None)], action_at, group_by
    )
    after = history_snapshot(
        [HistoryRow(1, "Medicine", 1, scheduled, action_at, status)], action_at, group_by
    )
    expected = Summary(1, 0, 0, 1, 0, 1, Decimal("0.00"))
    assert before.summary == after.summary == after.groups[0].summary == expected
    (dose,) = after.groups[0].doses
    assert dose.status == "bo_lo"


@pytest.mark.parametrize("group_by", list(GroupBy))
def test_valid_confirmation_synced_after_deadline_still_counts__AC3(group_by):
    # Distinguish a valid earlier taking time from an actual taking after +120 (QD-10).
    scheduled = NOW.replace(hour=8)
    taken = scheduled + timedelta(minutes=90)
    synced = scheduled + timedelta(minutes=121)
    confirmation = DoseConfirmation(uuid4(), 1, scheduled, taken)
    status = status_for_confirmation(confirmation, synced)
    assert status is DoseStatus.LATE
    result = history_snapshot(
        [HistoryRow(1, "Medicine", 1, scheduled, taken, status)], synced, group_by
    )
    assert (
        result.summary == result.groups[0].summary == Summary(1, 0, 1, 0, 0, 1, Decimal("100.00"))
    )
    assert result.groups[0].doses[0].taken_at == taken
