"""Task 3.21 snapshot migration, legacy preservation and actual role permissions."""

from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from test_notification_access import AT, assert_item
from test_notification_access import inbox as inbox


def test_upgrade_preserves_legacy_and_read_update__AC3(admin_engine, make):
    patient, family = make.user(), make.user()
    path = (
        Path(__file__).resolve().parents[2]
        / "supabase/migrations/20261021093454_family_alert_event_snapshot.sql"
    )
    with admin_engine.execution_options(isolation_level="READ COMMITTED").connect() as conn:
        tx = conn.begin()
        try:
            conn.execute(text("DROP TRIGGER notifications_require_snapshot ON notifications"))
            conn.execute(text("DROP FUNCTION require_notification_event_snapshot()"))
            conn.execute(text("DROP INDEX notifications_recipient_patient_idx"))
            conn.execute(text("DROP INDEX notifications_inbox_order_idx"))
            conn.execute(
                text(
                    "ALTER TABLE notifications DROP COLUMN medication_name, "
                    "DROP COLUMN scheduled_at"
                )
            )
            nid = conn.execute(
                text(
                    "INSERT INTO notifications "
                    "(user_id,about_patient_user_id,type,content,dedupe_key) "
                    "VALUES (:f,:p,'canh_bao_bo_lo_lieu_nguoi_than','Legacy',:k) RETURNING id"
                ),
                {"f": family, "p": patient, "k": uuid4().hex},
            ).scalar_one()
            before = conn.execute(
                text("SELECT id,user_id,content,is_read,created_at FROM notifications WHERE id=:i"),
                {"i": nid},
            ).one()
            # Run the actual migration statements inside rollback-only test isolation.
            sql = path.read_text("utf-8").removeprefix("BEGIN;").strip().removesuffix("COMMIT;")
            conn.connection.driver_connection.execute(sql)
            assert (
                conn.execute(
                    text(
                        "SELECT id,user_id,content,is_read,created_at "
                        "FROM notifications WHERE id=:i"
                    ),
                    {"i": nid},
                ).one()
                == before
            )
            assert conn.execute(
                text("SELECT medication_name,scheduled_at FROM notifications WHERE id=:i"),
                {"i": nid},
            ).one() == (None, None)
            conn.execute(text("GRANT api_role TO postgres"))
            conn.execute(text("SET LOCAL ROLE api_role"))
            conn.execute(text("UPDATE notifications SET is_read=true WHERE id=:i"), {"i": nid})
        finally:
            tx.rollback()


def test_legacy_null_snapshot_can_be_read_and_marked__AC3_AC4(inbox):
    d = inbox
    # Simulate retained legacy rows; never backfill from current schedules.
    d.db.execute(
        text("UPDATE notifications SET medication_name=NULL,scheduled_at=NULL WHERE id=:i"),
        {"i": d.nid},
    )
    body = assert_item(d.client.get(f"/notifications/{d.nid}", headers=d.headers))
    assert body["medication_name"] is body["scheduled_at"] is None
    body = assert_item(
        d.client.patch(f"/notifications/{d.nid}", headers=d.headers, json={"is_read": True})
    )
    assert body["is_read"] and body["medication_name"] is None


@pytest.mark.parametrize("name,at", [(None, AT), ("", AT), ("   ", AT), ("Valid", None)])
def test_new_insert_requires_snapshot__AC3(db, make, name, at):
    patient, family = make.user(), make.user()
    with pytest.raises(DBAPIError) as exc:
        db.execute(
            text(
                "INSERT INTO notifications (user_id,about_patient_user_id,type,content,"
                "dedupe_key,medication_name,scheduled_at) "
                "VALUES (:f,:p,'canh_bao_bo_lo_lieu_nguoi_than','Test',:k,:n,:at)"
            ),
            {"f": family, "p": patient, "k": uuid4().hex, "n": name, "at": at},
        )
    assert exc.value.orig.sqlstate == "23514"


@pytest.mark.parametrize("role", ["anon", "authenticated", "api_role", "worker_role"])
def test_snapshot_roles_rls_and_indexes__AC3_AC5(inbox, admin_engine, role):
    d = inbox
    with admin_engine.execution_options(isolation_level="READ COMMITTED").connect() as conn:
        tx = conn.begin()
        try:
            conn.execute(text(f"GRANT {role} TO postgres"))
            conn.execute(text(f"SET LOCAL ROLE {role}"))
            if role in ("anon", "authenticated"):
                with pytest.raises(DBAPIError):
                    with conn.begin_nested():
                        conn.execute(text("SELECT * FROM notifications"))
            elif role == "api_role":
                conn.execute(
                    text("UPDATE notifications SET is_read=true WHERE id=:i"), {"i": d.nid}
                )
                with pytest.raises(DBAPIError):
                    with conn.begin_nested():
                        conn.execute(
                            text("UPDATE notifications SET medication_name='tamper' WHERE id=:i"),
                            {"i": d.nid},
                        )
            else:
                conn.execute(
                    text(
                        "INSERT INTO notifications (user_id,about_patient_user_id,type,content,"
                        "dedupe_key,medication_name,scheduled_at) "
                        "VALUES (:f,:p,'canh_bao_bo_lo_lieu_nguoi_than','Test',:k,'Valid',:at)"
                    ),
                    {"f": d.family, "p": d.patient, "k": uuid4().hex, "at": AT},
                )
                with pytest.raises(DBAPIError):
                    with conn.begin_nested():
                        conn.execute(
                            text("UPDATE notifications SET is_read=true WHERE id=:i"), {"i": d.nid}
                        )
        finally:
            tx.rollback()
    assert d.db.execute(
        text("SELECT relrowsecurity FROM pg_class WHERE oid='public.notifications'::regclass")
    ).scalar_one()
    assert (
        d.db.execute(
            text(
                "SELECT count(*) FROM pg_policies WHERE tablename='notifications' "
                "AND roles && ARRAY['anon','authenticated']::name[]"
            )
        ).scalar_one()
        == 0
    )
    names = {
        r[0]
        for r in d.db.execute(
            text("SELECT indexname FROM pg_indexes WHERE tablename='notifications'")
        )
    }
    assert {
        "notifications_recipient_patient_idx",
        "notifications_inbox_order_idx",
        "notifications_dedupe_key_key",
    } <= names
    # Force index planning on the tiny test dataset; this proves eligibility, not production cost.
    with admin_engine.execution_options(isolation_level="READ COMMITTED").connect() as conn:
        tx = conn.begin()
        conn.execute(text("SET LOCAL enable_seqscan=off"))
        plan = "\n".join(
            r[0]
            for r in conn.execute(
                text(
                    "EXPLAIN SELECT id FROM notifications WHERE user_id=:u "
                    "ORDER BY created_at DESC,id DESC LIMIT 20"
                ),
                {"u": d.family},
            )
        )
        tx.rollback()
        assert "notifications_inbox_order_idx" in plan
