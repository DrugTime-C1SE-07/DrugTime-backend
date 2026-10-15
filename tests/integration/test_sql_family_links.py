"""Integration test cho SqlLinks.revoke (SCRUM-134, Backlog 3.26).

Kiểm tra:
1. Gỡ lần hai (idempotent) không đổi revoked_at (COALESCE(revoked_at, :revoked_at)).
2. Người lạ không thuộc liên kết gọi revoke -> không cập nhật bản ghi và trả về None.
"""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import text

from drugtime.modules.family.adapters.outbound.sql_links import SqlLinks
from drugtime.modules.family.domain.link import LinkStatus
from drugtime.shared.db import SqlUnitOfWork


def test_sql_revoke_idempotent_preserves_revoked_at(db, factory):
    """Gỡ lần hai không ghi đè revoked_at ban đầu."""
    patient_id = factory.user()
    family_id = factory.user()

    link_id = db.execute(
        text(
            "INSERT INTO caregiver_links (patient_user_id, family_user_id, status, sharing_enabled) "
            "VALUES (:p, :f, 'active', true) RETURNING id"
        ),
        {"p": patient_id, "f": family_id},
    ).scalar_one()

    t1 = datetime(2026, 10, 15, 8, 0, 0, tzinfo=UTC)
    t2 = t1 + timedelta(hours=2)

    links_repo = SqlLinks()
    uow = SqlUnitOfWork(db)

    # Lần 1: thu hồi thành công, revoked_at = t1
    first_res = links_repo.revoke(uow, link_id=link_id, caller_id=patient_id, now=t1)
    assert first_res is not None
    assert first_res.status is LinkStatus.REVOKED
    assert first_res.sharing_enabled is False
    assert first_res.revoked_at == t1

    # Lần 2: gọi lại với mốc thời gian t2 muộn hơn
    second_res = links_repo.revoke(uow, link_id=link_id, caller_id=patient_id, now=t2)
    assert second_res is not None
    assert second_res.status is LinkStatus.REVOKED
    # Nhờ COALESCE(revoked_at, :revoked_at), revoked_at vẫn giữ nguyên t1
    assert second_res.revoked_at == t1

    # Kiểm tra trực tiếp trong DB
    row = db.execute(
        text("SELECT status, revoked_at, sharing_enabled FROM caregiver_links WHERE id = :id"),
        {"id": link_id},
    ).one()
    assert row.status == "revoked"
    assert row.sharing_enabled is False
    assert row.revoked_at == t1


def test_sql_revoke_stranger_cannot_modify(db, factory):
    """Người lạ không có quyền thì câu UPDATE không khớp WHERE và trả về None."""
    patient_id = factory.user()
    family_id = factory.user()
    stranger_id = factory.user()

    link_id = db.execute(
        text(
            "INSERT INTO caregiver_links (patient_user_id, family_user_id, status, sharing_enabled) "
            "VALUES (:p, :f, 'active', true) RETURNING id"
        ),
        {"p": patient_id, "f": family_id},
    ).scalar_one()

    t = datetime(2026, 10, 15, 8, 30, 0, tzinfo=UTC)
    links_repo = SqlLinks()
    uow = SqlUnitOfWork(db)

    # Người lạ gọi revoke
    res = links_repo.revoke(uow, link_id=link_id, caller_id=stranger_id, now=t)
    assert res is None

    # Kiểm tra DB không bị thay đổi
    row = db.execute(
        text("SELECT status, revoked_at, sharing_enabled FROM caregiver_links WHERE id = :id"),
        {"id": link_id},
    ).one()
    assert row.status == "active"
    assert row.sharing_enabled is True
    assert row.revoked_at is None
