"""Integration tests for family link revoke (SCRUM-134, Backlog 3.26).

Adapter-level (SqlLinks.revoke) and use-case-level (manage_links.revoke_link)
tests against a real Postgres database.
"""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import text

from drugtime.modules.family.adapters.outbound.sql_links import SqlLinks
from drugtime.modules.family.application.manage_links import revoke_link
from drugtime.modules.family.domain.link import FamilyLinkError, LinkStatus
from drugtime.shared.db import SqlUnitOfWork
from drugtime.shared.errors import Forbidden


# ---- helpers ----

def _insert_link(db, patient_id, family_id, **kw):
    defaults = dict(status="active", sharing_enabled=True, revoked_at=None, rejected_at=None)
    defaults.update(kw)
    return db.execute(
        text(
            "INSERT INTO caregiver_links"
            " (patient_user_id, family_user_id, status, sharing_enabled, revoked_at, rejected_at)"
            " VALUES (:p, :f, CAST(:s AS link_status), :se, :ra, :reja) RETURNING id"
        ),
        dict(p=patient_id, f=family_id, s=defaults["status"], se=defaults["sharing_enabled"],
             ra=defaults["revoked_at"], reja=defaults["rejected_at"]),
    ).scalar_one()


def _link_row(db, link_id):
    return db.execute(
        text("SELECT status, revoked_at, rejected_at, sharing_enabled"
             " FROM caregiver_links WHERE id = :id"),
        dict(id=link_id),
    ).one()


# ---- adapter-level tests (SqlLinks.revoke) ----

def test_sql_revoke_idempotent_preserves_revoked_at(db, make):
    patient_id = make.user()
    family_id = make.user()
    link_id = _insert_link(db, patient_id, family_id)

    t1 = datetime(2026, 10, 15, 8, 0, 0, tzinfo=UTC)
    t2 = t1 + timedelta(hours=2)
    repo = SqlLinks()
    uow = SqlUnitOfWork(db)

    first = repo.revoke(uow, link_id=link_id, caller_id=patient_id, now=t1)
    assert first is not None
    assert first.status is LinkStatus.REVOKED
    assert first.sharing_enabled is False
    assert first.revoked_at == t1

    second = repo.revoke(uow, link_id=link_id, caller_id=patient_id, now=t2)
    assert second is not None
    assert second.status is LinkStatus.REVOKED
    assert second.revoked_at == t1

    row = _link_row(db, link_id)
    assert row.status == "revoked"
    assert row.sharing_enabled is False
    assert row.revoked_at == t1


def test_sql_revoke_stranger_cannot_modify(db, make):
    patient_id = make.user()
    family_id = make.user()
    stranger_id = make.user()
    link_id = _insert_link(db, patient_id, family_id)

    repo = SqlLinks()
    uow = SqlUnitOfWork(db)
    res = repo.revoke(uow, link_id=link_id, caller_id=stranger_id,
                      now=datetime(2026, 10, 15, 8, 30, 0, tzinfo=UTC))
    assert res is None

    row = _link_row(db, link_id)
    assert row.status == "active"
    assert row.sharing_enabled is True
    assert row.revoked_at is None


def test_sql_revoke_rejected_link_returns_none(db, make):
    patient_id = make.user()
    family_id = make.user()
    rejected_at = datetime(2026, 10, 14, 12, 0, 0, tzinfo=UTC)
    link_id = _insert_link(db, patient_id, family_id, status="rejected",
                           sharing_enabled=False, rejected_at=rejected_at)

    repo = SqlLinks()
    uow = SqlUnitOfWork(db)
    res = repo.revoke(uow, link_id=link_id, caller_id=patient_id,
                      now=datetime(2026, 10, 15, 9, 0, 0, tzinfo=UTC))
    assert res is None

    row = _link_row(db, link_id)
    assert row.status == "rejected"
    assert row.rejected_at == rejected_at
    assert row.revoked_at is None


# ---- use-case-level tests (revoke_link) ----

def test_revoke_active_link_sets_revoked_and_clears_sharing(db, make):
    """Revoke active -> 204-equivalent, status=revoked, sharing_enabled=false, rejected_at NULL."""
    patient_id = make.user()
    family_id = make.user()
    link_id = _insert_link(db, patient_id, family_id)

    uow = SqlUnitOfWork(db)
    now = datetime(2026, 10, 15, 10, 0, 0, tzinfo=UTC)
    result = revoke_link(uow, link_id=link_id, caller_id=patient_id, now=now, links=SqlLinks())

    assert result.status is LinkStatus.REVOKED
    assert result.sharing_enabled is False
    assert result.revoked_at == now

    row = _link_row(db, link_id)
    assert row.status == "revoked"
    assert row.revoked_at == now
    assert row.sharing_enabled is False
    assert row.rejected_at is None


def test_revoke_idempotent_via_use_case(db, make):
    """Second revoke keeps original revoked_at."""
    patient_id = make.user()
    family_id = make.user()
    link_id = _insert_link(db, patient_id, family_id)

    uow = SqlUnitOfWork(db)
    t1 = datetime(2026, 10, 15, 10, 0, 0, tzinfo=UTC)
    t2 = t1 + timedelta(hours=1)

    revoke_link(uow, link_id=link_id, caller_id=patient_id, now=t1, links=SqlLinks())
    result = revoke_link(uow, link_id=link_id, caller_id=patient_id, now=t2, links=SqlLinks())

    assert result.status is LinkStatus.REVOKED
    assert result.revoked_at == t1

    row = _link_row(db, link_id)
    assert row.revoked_at == t1


def test_stranger_revoke_rejected_link_gets_403(db, make):
    """Stranger + rejected link -> 403, NOT 422 (no info leak)."""
    patient_id = make.user()
    family_id = make.user()
    stranger_id = make.user()
    rejected_at = datetime(2026, 10, 14, 12, 0, 0, tzinfo=UTC)
    link_id = _insert_link(db, patient_id, family_id, status="rejected",
                           sharing_enabled=False, rejected_at=rejected_at)

    uow = SqlUnitOfWork(db)
    with pytest.raises(Forbidden, match="khong_co_quyen"):
        revoke_link(uow, link_id=link_id, caller_id=stranger_id,
                    now=datetime(2026, 10, 15, 9, 0, 0, tzinfo=UTC), links=SqlLinks())


def test_stranger_revoke_nonexistent_link_gets_403(db, make):
    """Stranger + nonexistent link -> 403, same detail as above."""
    stranger_id = make.user()
    uow = SqlUnitOfWork(db)
    with pytest.raises(Forbidden, match="khong_co_quyen"):
        revoke_link(uow, link_id=999999, caller_id=stranger_id,
                    now=datetime(2026, 10, 15, 9, 0, 0, tzinfo=UTC), links=SqlLinks())


def test_owner_revoke_rejected_link_gets_422(db, make):
    """Owner + rejected link -> 422 invalid_link_transition."""
    patient_id = make.user()
    family_id = make.user()
    rejected_at = datetime(2026, 10, 14, 12, 0, 0, tzinfo=UTC)
    link_id = _insert_link(db, patient_id, family_id, status="rejected",
                           sharing_enabled=False, rejected_at=rejected_at)

    uow = SqlUnitOfWork(db)
    with pytest.raises(FamilyLinkError, match="cannot transition family link from rejected to revoked"):
        revoke_link(uow, link_id=link_id, caller_id=patient_id,
                    now=datetime(2026, 10, 15, 9, 0, 0, tzinfo=UTC), links=SqlLinks())
