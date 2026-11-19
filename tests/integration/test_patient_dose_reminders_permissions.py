"""Database regressions for the reminder notification snapshot boundary."""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError


@pytest.mark.parametrize(
    ("medication_name", "scheduled_at"),
    [(None, "2026-11-19T03:00:00Z"), ("  ", "2026-11-19T03:00:00Z"), ("Thuoc A", None)],
)
def test_family_alert_still_requires_complete_snapshot__AC22(
    db, make, medication_name, scheduled_at
):
    patient = make.user()
    with pytest.raises(IntegrityError) as error:
        db.execute(
            text("""
                INSERT INTO notifications
                    (user_id, about_patient_user_id, type, content, medication_name, scheduled_at)
                VALUES (:patient, :patient, 'canh_bao_bo_lo_lieu_nguoi_than',
                        'Test alert', :name, :scheduled_at)
            """),
            {"patient": patient, "name": medication_name, "scheduled_at": scheduled_at},
        )
    assert error.value.orig.sqlstate == "23514"


def test_api_role_can_insert_generic_reminder_without_snapshot__AC09(db, make):
    from drugtime.shared.db import get_engine

    patient = make.user()
    with get_engine().begin() as connection:
        assert connection.execute(text("SELECT current_user")).scalar_one() == "api_role"
        connection.execute(
            text("""
                INSERT INTO notifications
                    (user_id, about_patient_user_id, type, content, created_at)
                VALUES (:patient, :patient, 'nhac_uong_thuoc', 'Test reminder', now())
            """),
            {"patient": patient},
        )
    row = db.execute(
        text("SELECT medication_name, scheduled_at FROM notifications WHERE user_id = :patient"),
        {"patient": patient},
    ).one()
    assert row.medication_name is None and row.scheduled_at is None


def test_family_alert_with_complete_snapshot_is_accepted__AC22(db, make):
    patient = make.user()
    db.execute(
        text("""
            INSERT INTO notifications
                (user_id, about_patient_user_id, type, content, medication_name, scheduled_at)
            VALUES (:patient, :patient, 'canh_bao_bo_lo_lieu_nguoi_than',
                    'Test alert', 'Thuoc A', '2026-11-19T03:00:00Z')
        """),
        {"patient": patient},
    )


@pytest.mark.parametrize("role", ["anon", "authenticated", "service_role"])
@pytest.mark.parametrize("table", ["dose_reminder_requests", "dose_reminder_outbox"])
def test_client_roles_cannot_read_reminder_tables__AC20(db, role, table):
    assert not db.execute(
        text("SELECT has_table_privilege(:role, :table, 'SELECT')"),
        {"role": role, "table": table},
    ).scalar_one()


def test_reminder_grants_preserve_identity_and_audit__AC20(db):
    def permitted(role, table, column, privilege):
        return db.execute(
            text("SELECT has_column_privilege(:role, :table, :column, :privilege)"),
            {"role": role, "table": table, "column": column, "privilege": privilege},
        ).scalar_one()

    assert not permitted("api_role", "dose_reminder_requests", "status", "UPDATE")
    assert not permitted("worker_role", "dose_reminder_requests", "patient_user_id", "UPDATE")
    assert permitted("worker_role", "dose_reminder_requests", "status", "UPDATE")
    for role in ("api_role", "worker_role"):
        for privilege in ("UPDATE", "DELETE", "TRUNCATE"):
            assert not db.execute(
                text("SELECT has_table_privilege(:role, 'access_logs', :privilege)"),
                {"role": role, "privilege": privilege},
            ).scalar_one()


@pytest.mark.parametrize(
    ("scope", "role", "result", "allowed"),
    [
        ("lich_su_tuan_thu", "family", "allowed", True),
        ("lich_su_tuan_thu", "khong_co_quyen", "denied", True),
        ("danh_sach_thuoc", "family", "allowed", False),
        ("lich_su_tuan_thu", "admin", "denied", False),
    ],
)
def test_worker_audit_insert_policy__AC13_AC20(
    db, make, role_engines, scope, role, result, allowed
):
    patient, family = make.user(), make.user()
    engine = role_engines["worker_role"]
    with engine.connect() as conn:
        transaction = conn.begin()
        try:
            assert conn.execute(text("SELECT current_user")).scalar_one() == "worker_role"
            statement = text(
                "INSERT INTO access_logs "
                "(actor_user_id, actor_role, patient_user_id, data_scope, result, "
                "rejection_reason, accessed_at) "
                "VALUES (:actor, :role, :patient, :scope, :result, :reason, now())"
            )
            values = {
                "actor": family,
                "role": role,
                "patient": patient,
                "scope": scope,
                "result": result,
                "reason": "test" if result == "denied" else None,
            }
            if allowed:
                conn.execute(statement, values)
            else:
                with pytest.raises(DBAPIError) as error:
                    conn.execute(statement, values)
                assert error.value.orig.sqlstate == "42501"
        finally:
            transaction.rollback()


def test_worker_audit_sequence_and_append_only_triggers__AC20(db):
    assert db.execute(
        text("SELECT has_sequence_privilege('worker_role', 'access_logs_id_seq', 'USAGE')")
    ).scalar_one()
    assert (
        db.execute(
            text(
                "SELECT count(*) FROM pg_trigger WHERE tgrelid = 'access_logs'::regclass "
                "AND tgname IN ('access_logs_append_only', 'access_logs_no_truncate') "
                "AND tgenabled <> 'D'"
            )
        ).scalar_one()
        == 2
    )
