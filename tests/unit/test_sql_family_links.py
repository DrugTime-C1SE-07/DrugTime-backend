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
    patient_id=None, family_id=None, *, status="pending", revoked_at=None, rejected_at=None
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
    )


def test_sql_find_pair_uses_patient_and_family_roles__AC6():
    patient_id = uuid4()
    family_id = uuid4()
    uow = FakeUow([_row(patient_id, family_id)])

    result = SqlLinks().find_by_pair(uow, patient_id, family_id)

    assert result is not None
    assert result.patient_user_id == patient_id
    assert result.family_user_id == family_id
    params = uow.connection.calls[0][1]
    assert params == {"patient_id": patient_id, "family_id": family_id}


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
    assert params == {"patient_id": patient_id, "family_id": family_id, "status": "pending"}


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
