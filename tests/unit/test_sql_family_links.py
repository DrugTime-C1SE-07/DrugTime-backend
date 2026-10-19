from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

from drugtime.modules.family.adapters.outbound.sql_links import SqlLinks
from drugtime.modules.family.domain.link import FamilyLink, LinkStatus


class FakeResult:
    def __init__(self, row=None):
        self.row = row

    def first(self):
        return self.row

    def one(self):
        return self.row

    def scalar(self):
        return self.row

    def __iter__(self):
        if isinstance(self.row, list):
            return iter(self.row)
        return iter([] if self.row is None else [self.row])


class FakeConnection:
    def __init__(self, rows):
        self.rows = list(rows)
        self.calls = []

    def execute(self, statement, params=None):
        self.calls.append((str(statement), params or {}))
        return FakeResult(self.rows.pop(0) if self.rows else None)


class FakeUow:
    def __init__(self, rows):
        self.connection = FakeConnection(rows)


def _row(
    patient_id=None,
    family_id=None,
    *,
    status="pending",
    revoked_at=None,
    rejected_at=None,
    client_uuid=None,
):
    return SimpleNamespace(
        id=77,
        patient_user_id=patient_id or uuid4(),
        family_user_id=family_id or uuid4(),
        status=status,
        sharing_enabled=False,
        linked_at=datetime(2026, 10, 7, tzinfo=UTC),
        revoked_at=revoked_at,
        rejected_at=rejected_at,
        client_uuid=client_uuid,
    )


def test_find_open_by_pair_filters_pending_active__AC6():
    patient_id = uuid4()
    family_id = uuid4()
    uow = FakeUow([_row(patient_id, family_id)])

    result = SqlLinks().find_open_by_pair(uow, patient_id, family_id)

    assert result is not None
    assert result.patient_user_id == patient_id
    assert result.family_user_id == family_id
    sql, params = uow.connection.calls[0]
    assert "patient_user_id = :patient_id AND family_user_id = :family_id" in sql
    assert "status IN ('pending', 'active')" in sql
    assert params == {"patient_id": patient_id, "family_id": family_id}


def test_find_open_by_pair_none_when_absent__AC9():
    assert SqlLinks().find_open_by_pair(FakeUow([None]), uuid4(), uuid4()) is None


def test_sql_create_link_inserts_pending_with_patient_family_roles__AC1():
    patient_id = uuid4()
    family_id = uuid4()
    uow = FakeUow([_row(patient_id, family_id)])

    result = SqlLinks().create(
        uow,
        FamilyLink(
            id=None,
            patient_user_id=patient_id,
            family_user_id=family_id,
            status=LinkStatus.PENDING,
        ),
    )

    assert result.status is LinkStatus.PENDING
    params = uow.connection.calls[0][1]
    assert params == {
        "patient_id": patient_id,
        "family_id": family_id,
        "status": "pending",
        "client_uuid": None,
    }


def test_sql_update_status_sets_revoked_at_only_for_revoked__AC7_AC8():
    revoked_at = datetime(2026, 10, 7, tzinfo=UTC)
    uow = FakeUow([_row(status="revoked", revoked_at=revoked_at)])

    result = SqlLinks().update_status(uow, 77, LinkStatus.REVOKED, revoked_at, None)

    assert result.status is LinkStatus.REVOKED
    assert result.revoked_at == revoked_at
    assert uow.connection.calls[0][1] == {
        "id": 77,
        "status": "revoked",
        "revoked_at": revoked_at,
        "rejected_at": None,
    }


def test_sql_update_status_sets_rejected_at_only_for_rejected():
    rejected_at = datetime(2026, 10, 7, tzinfo=UTC)
    uow = FakeUow([_row(status="rejected", rejected_at=rejected_at)])

    result = SqlLinks().update_status(uow, 77, LinkStatus.REJECTED, None, rejected_at)

    assert result.status is LinkStatus.REJECTED
    assert result.revoked_at is None
    assert result.rejected_at == rejected_at
    assert uow.connection.calls[0][1] == {
        "id": 77,
        "status": "rejected",
        "revoked_at": None,
        "rejected_at": rejected_at,
    }


def test_sql_active_sharing_queries_keep_existing_filter__AC11():
    patient_id = uuid4()
    family_id = uuid4()
    uow = FakeUow([SimpleNamespace(id=1), [SimpleNamespace(family_user_id=family_id)]])
    links = SqlLinks()

    assert links.has_active_sharing_link(uow, patient_id, family_id)
    assert links.sharing_family_ids(uow, patient_id) == [family_id]

    first_sql = uow.connection.calls[0][0]
    second_sql = uow.connection.calls[1][0]
    assert "status = 'active' AND sharing_enabled = true" in first_sql
    assert "status = 'active' AND sharing_enabled = true" in second_sql


def test_sql_erase_deletes_link_code_without_family_column__AC14():
    user_id = uuid4()
    uow = FakeUow([])

    SqlLinks().erase(uow, user_id)

    link_code_sql = [sql for sql, _ in uow.connection.calls if "link_codes" in sql]
    assert link_code_sql == ["DELETE FROM link_codes WHERE patient_user_id = :u"]
    assert all(params == {"u": user_id} for _, params in uow.connection.calls)


# --- task 3.13 ----------------------------------------------------------------------------


def _sql(uow, i=0):
    return " ".join(uow.connection.calls[i][0].split())


def test_lock_sender_uses_advisory_xact_lock__AC13():
    family_id = uuid4()
    uow = FakeUow([])

    SqlLinks().lock_sender(uow, family_id)

    assert "pg_advisory_xact_lock(hashtextextended(" in _sql(uow)
    assert "'family_link_request:'" in _sql(uow)
    assert uow.connection.calls[0][1] == {"family_id": family_id}


def test_find_by_client_uuid_scoped_to_family__AC29_AC30():
    family_id, key = uuid4(), uuid4()
    uow = FakeUow([_row(family_id=family_id, client_uuid=key)])

    result = SqlLinks().find_by_client_uuid(uow, family_id, key)

    assert result is not None and result.client_uuid == key
    assert "WHERE family_user_id = :family_id AND client_uuid = :client_uuid" in _sql(uow)
    assert uow.connection.calls[0][1] == {"family_id": family_id, "client_uuid": key}


def test_create_writes_client_uuid__AC29():
    patient_id, family_id, key = uuid4(), uuid4(), uuid4()
    uow = FakeUow([_row(patient_id, family_id, client_uuid=key)])

    result = SqlLinks().create(
        uow, FamilyLink(None, patient_id, family_id, LinkStatus.PENDING, client_uuid=key)
    )

    assert result.client_uuid == key
    assert uow.connection.calls[0][1]["client_uuid"] == key
    assert "sharing_enabled, client_uuid)" in _sql(uow)
    assert "VALUES (:patient_id, :family_id, :status, false, :client_uuid)" in _sql(uow)


def test_count_created_since__AC14():
    family_id = uuid4()
    since = datetime(2026, 10, 15, 17, tzinfo=UTC)
    uow = FakeUow([7])

    assert SqlLinks().count_created_since(uow, family_id, since) == 7
    assert "WHERE family_user_id = :family_id AND linked_at >= :since" in _sql(uow)
    assert uow.connection.calls[0][1] == {"family_id": family_id, "since": since}


def test_rejection_streak_sql__AC8b():
    patient_id, family_id = uuid4(), uuid4()
    last = datetime(2026, 10, 16, tzinfo=UTC)
    uow = FakeUow([SimpleNamespace(streak=5, last_rejected_at=last)])

    assert SqlLinks().rejection_streak(uow, patient_id, family_id) == (5, last)
    sql = _sql(uow)
    assert "count(*) AS streak, max(rejected_at) AS last_rejected_at" in sql
    assert "status = 'rejected'" in sql
    # Chỉ đếm dòng rejected sau dòng không phải rejected cuối cùng (chấp thuận cắt chuỗi).
    assert "AND id > COALESCE(( SELECT max(id) FROM caregiver_links" in sql
    assert "AND status <> 'rejected'" in sql
    assert uow.connection.calls[0][1] == {"patient_id": patient_id, "family_id": family_id}


def test_erase_deletes_attempts__AC19():
    user_id = uuid4()
    uow = FakeUow([])

    SqlLinks().erase(uow, user_id)

    sqls = [" ".join(sql.split()) for sql, _ in uow.connection.calls]
    assert "DELETE FROM link_request_attempts WHERE family_user_id = :u" in sqls
    assert all(params == {"u": user_id} for _, params in uow.connection.calls)
