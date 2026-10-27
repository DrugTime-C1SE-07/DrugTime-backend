"""Integration tests for family link revoke (SCRUM-134, Backlog 3.26).

Adapter-level (SqlLinks.revoke) and use-case-level (manage_links.revoke_link)
tests against a real Postgres database.
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text

from drugtime.modules.family.adapters.outbound.sql_links import SqlLinks
from drugtime.modules.family.application.manage_links import (
    revoke_link_as_member as revoke_link,
)
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
        dict(
            p=patient_id,
            f=family_id,
            s=defaults["status"],
            se=defaults["sharing_enabled"],
            ra=defaults["revoked_at"],
            reja=defaults["rejected_at"],
        ),
    ).scalar_one()


def _link_row(db, link_id):
    return db.execute(
        text(
            "SELECT status, revoked_at, rejected_at, sharing_enabled"
            " FROM caregiver_links WHERE id = :id"
        ),
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
    res = repo.revoke(
        uow,
        link_id=link_id,
        caller_id=stranger_id,
        now=datetime(2026, 10, 15, 8, 30, 0, tzinfo=UTC),
    )
    assert res is None

    row = _link_row(db, link_id)
    assert row.status == "active"
    assert row.sharing_enabled is True
    assert row.revoked_at is None


def test_sql_revoke_rejected_link_returns_none(db, make):
    patient_id = make.user()
    family_id = make.user()
    rejected_at = datetime(2026, 10, 14, 12, 0, 0, tzinfo=UTC)
    link_id = _insert_link(
        db, patient_id, family_id, status="rejected", sharing_enabled=False, rejected_at=rejected_at
    )

    repo = SqlLinks()
    uow = SqlUnitOfWork(db)
    res = repo.revoke(
        uow, link_id=link_id, caller_id=patient_id, now=datetime(2026, 10, 15, 9, 0, 0, tzinfo=UTC)
    )
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
    link_id = _insert_link(
        db, patient_id, family_id, status="rejected", sharing_enabled=False, rejected_at=rejected_at
    )

    uow = SqlUnitOfWork(db)
    with pytest.raises(Forbidden, match="khong_co_quyen"):
        revoke_link(
            uow,
            link_id=link_id,
            caller_id=stranger_id,
            now=datetime(2026, 10, 15, 9, 0, 0, tzinfo=UTC),
            links=SqlLinks(),
        )


def test_stranger_revoke_nonexistent_link_gets_403(db, make):
    """Stranger + nonexistent link -> 403, same detail as above."""
    stranger_id = make.user()
    uow = SqlUnitOfWork(db)
    with pytest.raises(Forbidden, match="khong_co_quyen"):
        revoke_link(
            uow,
            link_id=999999,
            caller_id=stranger_id,
            now=datetime(2026, 10, 15, 9, 0, 0, tzinfo=UTC),
            links=SqlLinks(),
        )


def test_owner_revoke_rejected_link_gets_422(db, make):
    """Owner + rejected link -> 422 invalid_link_transition."""
    patient_id = make.user()
    family_id = make.user()
    rejected_at = datetime(2026, 10, 14, 12, 0, 0, tzinfo=UTC)
    link_id = _insert_link(
        db, patient_id, family_id, status="rejected", sharing_enabled=False, rejected_at=rejected_at
    )

    uow = SqlUnitOfWork(db)
    with pytest.raises(FamilyLinkError, match="invalid_link_transition"):
        revoke_link(
            uow,
            link_id=link_id,
            caller_id=patient_id,
            now=datetime(2026, 10, 15, 9, 0, 0, tzinfo=UTC),
            links=SqlLinks(),
        )


def test_revoke_already_revoked_with_sharing_enabled_true_clears_sharing_db(db, make):
    """(Hạng mục e) Link revoked còn sharing_enabled=true (dữ liệu cũ)
    được ép về false, giữ nguyên revoked_at."""
    patient_id = make.user()
    family_id = make.user()
    t1 = datetime(2026, 10, 15, 8, 0, 0, tzinfo=UTC)
    t2 = t1 + timedelta(hours=2)
    link_id = _insert_link(
        db, patient_id, family_id, status="revoked", sharing_enabled=True, revoked_at=t1
    )

    uow = SqlUnitOfWork(db)
    result = revoke_link(uow, link_id=link_id, caller_id=patient_id, now=t2, links=SqlLinks())

    assert result.status is LinkStatus.REVOKED
    assert result.sharing_enabled is False
    assert result.revoked_at == t1

    row = _link_row(db, link_id)
    assert row.status == "revoked"
    assert row.sharing_enabled is False
    assert row.revoked_at == t1

    # Lần gỡ tiếp theo khi sharing_enabled đã false -> idempotent, không đổi
    t3 = t2 + timedelta(hours=1)
    result_again = revoke_link(uow, link_id=link_id, caller_id=patient_id, now=t3, links=SqlLinks())
    assert result_again.status is LinkStatus.REVOKED
    assert result_again.sharing_enabled is False
    assert result_again.revoked_at == t1

    row_again = _link_row(db, link_id)
    assert row_again.status == "revoked"
    assert row_again.sharing_enabled is False
    assert row_again.revoked_at == t1


def test_family_member_self_leave_db(db, make):
    """(Hạng mục h) Family member tự rời liên kết qua use-case (DB thật):
    trả về 204-equivalent và DB đúng."""
    patient_id = make.user()
    family_id = make.user()
    link_id = _insert_link(db, patient_id, family_id, status="active", sharing_enabled=True)

    uow = SqlUnitOfWork(db)
    now = datetime(2026, 10, 15, 10, 0, 0, tzinfo=UTC)
    result = revoke_link(uow, link_id=link_id, caller_id=family_id, now=now, links=SqlLinks())

    assert result.status is LinkStatus.REVOKED
    assert result.sharing_enabled is False
    assert result.revoked_at == now

    row = _link_row(db, link_id)
    assert row.status == "revoked"
    assert row.sharing_enabled is False
    assert row.revoked_at == now
    assert row.rejected_at is None


def test_revoke_pending_link_db(db, make):
    """(Hạng mục h) Gỡ link pending qua use-case (DB thật):
    ghi nhận hành vi thực tế -> revoked, sharing_enabled=False."""
    patient_id = make.user()
    family_id = make.user()
    link_id = _insert_link(db, patient_id, family_id, status="pending", sharing_enabled=False)

    uow = SqlUnitOfWork(db)
    now = datetime(2026, 10, 15, 10, 0, 0, tzinfo=UTC)
    result = revoke_link(uow, link_id=link_id, caller_id=patient_id, now=now, links=SqlLinks())

    assert result.status is LinkStatus.REVOKED
    assert result.sharing_enabled is False
    assert result.revoked_at == now

    row = _link_row(db, link_id)
    assert row.status == "revoked"
    assert row.sharing_enabled is False
    assert row.revoked_at == now
    assert row.rejected_at is None


def test_stranger_revoke_active_link_gets_403_and_db_unchanged(db, make):
    """(Hạng mục h) Người lạ gỡ link active qua use-case (DB thật):
    nhận 403 và DB giữ nguyên active."""
    patient_id = make.user()
    family_id = make.user()
    stranger_id = make.user()
    link_id = _insert_link(db, patient_id, family_id, status="active", sharing_enabled=True)

    uow = SqlUnitOfWork(db)
    with pytest.raises(Forbidden, match="khong_co_quyen"):
        revoke_link(
            uow,
            link_id=link_id,
            caller_id=stranger_id,
            now=datetime(2026, 10, 15, 9, 0, 0, tzinfo=UTC),
            links=SqlLinks(),
        )

    row = _link_row(db, link_id)
    assert row.status == "active"
    assert row.sharing_enabled is True
    assert row.revoked_at is None


@pytest.mark.parametrize("revoker", ["patient", "family"])
def test_e2e_delete_link_immediate_403_and_audit(client, db, make, auth, scheduled_body, revoker):
    """(Hạng mục i) End-to-end:
    - Family gọi GET /medications/{id} -> 200
    - Gỡ link bằng DELETE qua HTTP (một ca bởi patient, một ca bởi Family) -> 204
    - Family gọi lại -> 403 khong_co_quyen
    - Đúng 1 dòng access_logs result=\'denied\' cho lượt đó
    - Thời gian từ lúc DELETE trả về tới lúc bị chặn < 5 giây (QA.02)
    - Dòng caregiver_links còn tồn tại, status=\'revoked\', sharing_enabled=false.
    """
    import time

    patient = make.user()
    family = make.family_of(patient)
    link_id = db.execute(
        text("SELECT id FROM caregiver_links WHERE patient_user_id = :p AND family_user_id = :f"),
        {"p": patient, "f": family},
    ).scalar_one()

    # Dựng thuốc cho patient
    med_body = scheduled_body(make.catalog_medication(), stock_quantity=10)
    res_create = client.post("/medications", json=med_body, headers=auth(patient))
    assert res_create.status_code == 201
    med_id = res_create.json()["id"]

    # 1. Family đọc thành công trước khi gỡ
    res_get_before = client.get(f"/medications/{med_id}", headers=auth(family))
    assert res_get_before.status_code == 200

    # 2. Gỡ link bằng DELETE qua HTTP
    revoker_user = patient if revoker == "patient" else family
    start_time = time.perf_counter()
    del_res = client.delete(f"/links/{link_id}", headers=auth(revoker_user))
    assert del_res.status_code == 204

    # 3. Request kế tiếp của Family bị 403 ngay lập tức (< 5s)
    res_get_after = client.get(f"/medications/{med_id}", headers=auth(family))
    elapsed = time.perf_counter() - start_time
    assert res_get_after.status_code == 403
    assert res_get_after.json() == {"detail": "khong_co_quyen"}
    assert elapsed < 5.0, f"Mất quyền truy cập quá 5 giây: {elapsed:.3f}s"

    # 4. Kiểm tra access_logs: lượt sau bị ghi đúng 1 dòng result=\'denied\'
    logs = make.access_logs(patient)
    # Lượt 1 được \'allowed\' (vai trò family), lượt 2 bị \'denied\' (vai trò khong_co_quyen)
    assert len(logs) == 2
    assert logs[0]["result"] == "allowed"
    assert logs[1]["result"] == "denied"
    assert logs[1]["actor_user_id"] == family
    assert logs[1]["rejection_reason"] == "khong_co_quyen"

    # 5. Dòng caregiver_links vẫn tồn tại: status='revoked', sharing_enabled=false
    row = _link_row(db, link_id)
    assert row.status == "revoked"
    assert row.sharing_enabled is False
    assert row.revoked_at is not None


def test_worker_alert_suppressed_after_revoke_link(db, make):
    """(Hạng mục j) Worker alert:
    - Đối chứng dương: link active -> scan_and_notify gửi cảnh báo cho Family qua fake Notifier.
    - Sau khi gỡ link: quét lại -> KHÔNG gửi cho người này nữa.
    Ghi chú: re-check quyền ngay trước notifier.send (QD-29) là ngoài phạm vi của task 3.26.
    """
    from types import SimpleNamespace

    from drugtime.modules.adherence.adapters.outbound.other_modules import AccessGuardAdapter
    from drugtime.modules.adherence.application.scan_missed_doses import scan_and_notify
    from drugtime.modules.adherence.domain.dose import LATE_CONFIRMATION_WINDOW

    patient_id = make.user()
    family_id = make.family_of(patient_id)
    link_id = db.execute(
        text("SELECT id FROM caregiver_links WHERE patient_user_id = :p AND family_user_id = :f"),
        {"p": patient_id, "f": family_id},
    ).scalar_one()

    # Fake ports cho scan_missed_doses
    class FakeCursor:
        def get(self, uow):
            return datetime(2026, 10, 15, 7, 0, tzinfo=UTC)

        def advance(self, uow, until):
            pass

    class FakeSchedules:
        def __init__(self, occurrences):
            self.occurrences = occurrences

        def occurrences_between(self, uow, start, end):
            return self.occurrences

        def alert_context(self, uow, schedule_id, patient_id):
            return "Test medication"

    class FakeDoseLogs:
        def __init__(self):
            self.missed = []

        def mark_missed(self, uow, schedule_id, scheduled_at):
            self.missed.append((schedule_id, scheduled_at))
            return len(self.missed)

    class FakeDeviceTokens:
        def android_tokens(self, uow, user_ids):
            return [(uid, f"token-{uid}") for uid in user_ids]

    class FakeNotifications:
        def __init__(self):
            self.created = []

        def create_missed_alert(
            self,
            uow,
            recipient_id,
            patient_id,
            dedupe_key,
            content=None,
            *,
            medication_name,
            scheduled_at,
        ):
            nid = len(self.created) + 1
            self.created.append((nid, recipient_id, patient_id, dedupe_key))
            return nid

    # 3.19: patient đã đồng bộ sau hạn chót nên liều được xác minh ngay; hàng chờ không dùng.
    class SyncedCheckpoints:
        def get_many(self, uow, user_ids):
            return {uid: datetime(2100, 1, 1, tzinfo=UTC) for uid in user_ids}

    class NoPending:
        def add(self, uow, occ):
            return False

        def verified(self, uow, now):
            return []

        def remove(self, uow, occ):
            pass

        def purge_recorded(self, uow):
            pass

    class FakeNotifier:
        def __init__(self):
            self.sent_alerts = []

        def send(self, alerts):
            self.sent_alerts.extend(alerts)

    # 1. ĐỐI CHỨNG DƯƠNG: Link đang active -> Family nhận được alert
    occ1 = SimpleNamespace(
        schedule_id=1,
        scheduled_at=datetime(2026, 10, 15, 7, 30, tzinfo=UTC),
        patient_id=patient_id,
    )
    notifier1 = FakeNotifier()

    from contextlib import contextmanager

    @contextmanager
    def uow_factory():
        yield SqlUnitOfWork(db)

    count1 = scan_and_notify(
        uow_factory=uow_factory,
        notifier=notifier1,
        now=datetime(2026, 10, 15, 10, 0, tzinfo=UTC),
        grace=LATE_CONFIRMATION_WINDOW,
        overlap=timedelta(minutes=5),
        cursor=FakeCursor(),
        schedules=FakeSchedules([occ1]),
        dose_logs=FakeDoseLogs(),
        access=AccessGuardAdapter(),
        tokens=FakeDeviceTokens(),
        notifications=FakeNotifications(),
        checkpoints=SyncedCheckpoints(),
        pending=NoPending(),
    )
    assert count1 == 1
    assert len(notifier1.sent_alerts) == 1
    assert notifier1.sent_alerts[0].recipient_id == family_id

    # 2. GỠ LIÊN KẾT (bởi patient)
    uow = SqlUnitOfWork(db)
    revoke_link(
        uow,
        link_id=link_id,
        caller_id=patient_id,
        now=datetime(2026, 10, 15, 10, 30, tzinfo=UTC),
        links=SqlLinks(),
    )

    # 3. QUÉT LẠI: Liều bỏ lỡ tiếp theo KHÔNG gửi cho Family nữa
    occ2 = SimpleNamespace(
        schedule_id=2,
        scheduled_at=datetime(2026, 10, 15, 11, 0, tzinfo=UTC),
        patient_id=patient_id,
    )
    notifier2 = FakeNotifier()
    count2 = scan_and_notify(
        uow_factory=uow_factory,
        notifier=notifier2,
        now=datetime(2026, 10, 15, 13, 30, tzinfo=UTC),
        grace=LATE_CONFIRMATION_WINDOW,
        overlap=timedelta(minutes=5),
        cursor=FakeCursor(),
        schedules=FakeSchedules([occ2]),
        dose_logs=FakeDoseLogs(),
        access=AccessGuardAdapter(),
        tokens=FakeDeviceTokens(),
        notifications=FakeNotifications(),
        checkpoints=SyncedCheckpoints(),
        pending=NoPending(),
    )
    assert count2 == 0
    assert len(notifier2.sent_alerts) == 0
