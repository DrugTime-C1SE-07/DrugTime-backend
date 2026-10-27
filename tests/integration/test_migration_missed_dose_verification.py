"""Task 3.19 (P27): grant, RLS và ràng buộc của dose_sync_checkpoints và
missed_dose_pending_verifications, kiểm bằng api_role/worker_role thật."""

from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, ProgrammingError
from test_adherence_history_api import DAY, HistoryData

CHECKPOINTS = "dose_sync_checkpoints"
PENDING = "missed_dose_pending_verifications"


@pytest.fixture
def patient_schedule(db, make, client, auth):
    patient = make.user()
    occ = HistoryData(db, make, client, auth, patient).schedule(DAY + timedelta(hours=8))
    return patient, occ


def attempt(engine, sql, params):
    """Chạy một câu bằng role thật trong transaction luôn rollback; trả 'ok' hoặc 'denied'."""
    with engine.connect() as c:
        tx = c.begin()
        try:
            c.execute(text(sql), params)
            return "ok"
        except ProgrammingError as exc:
            assert "permission denied" in str(exc)
            return "denied"
        finally:
            tx.rollback()


def statements(patient, occ):
    p = {"u": patient, "s": occ.schedule_id, "at": occ.scheduled_at}
    return {
        (CHECKPOINTS, "SELECT"): (f"SELECT * FROM {CHECKPOINTS} WHERE user_id = :u", p),
        (CHECKPOINTS, "INSERT"): (
            f"INSERT INTO {CHECKPOINTS} (user_id, synced_at) VALUES (:u, now())",
            p,
        ),
        (CHECKPOINTS, "UPDATE"): (
            f"UPDATE {CHECKPOINTS} SET synced_at = now() WHERE user_id = :u",
            p,
        ),
        (CHECKPOINTS, "DELETE"): (f"DELETE FROM {CHECKPOINTS} WHERE user_id = :u", p),
        (PENDING, "SELECT"): (f"SELECT * FROM {PENDING} WHERE patient_user_id = :u", p),
        (PENDING, "INSERT"): (
            f"INSERT INTO {PENDING} (medication_schedule_id, scheduled_at, patient_user_id) "
            "VALUES (:s, :at, :u)",
            p,
        ),
        (PENDING, "UPDATE"): (
            f"UPDATE {PENDING} SET created_at = now() WHERE patient_user_id = :u",
            p,
        ),
        (PENDING, "DELETE"): (f"DELETE FROM {PENDING} WHERE patient_user_id = :u", p),
    }


GRANTS = {
    "api_role": {
        (CHECKPOINTS, "SELECT"): "ok",
        (CHECKPOINTS, "INSERT"): "ok",
        (CHECKPOINTS, "UPDATE"): "ok",
        (CHECKPOINTS, "DELETE"): "denied",
        (PENDING, "SELECT"): "denied",
        (PENDING, "INSERT"): "denied",
        (PENDING, "UPDATE"): "denied",
        (PENDING, "DELETE"): "denied",
    },
    "worker_role": {
        (CHECKPOINTS, "SELECT"): "ok",
        (CHECKPOINTS, "INSERT"): "denied",
        (CHECKPOINTS, "UPDATE"): "denied",
        (CHECKPOINTS, "DELETE"): "ok",
        (PENDING, "SELECT"): "ok",
        (PENDING, "INSERT"): "ok",
        (PENDING, "UPDATE"): "denied",
        (PENDING, "DELETE"): "ok",
    },
}


@pytest.mark.parametrize("role", ["api_role", "worker_role"])
def test_role_grants_are_minimal(role, role_engines, patient_schedule):
    patient, occ = patient_schedule
    sql = statements(patient, occ)
    actual = {key: attempt(role_engines[role], *sql[key]) for key in sql}
    assert actual == GRANTS[role]


@pytest.mark.parametrize("table", [CHECKPOINTS, PENDING])
def test_rls_on_and_client_roles_have_no_access(db, table):
    assert db.execute(
        text("SELECT relrowsecurity FROM pg_class WHERE oid = CAST(:t AS regclass)"),
        {"t": table},
    ).scalar_one()
    for role in ("anon", "authenticated"):
        for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE"):
            assert not db.execute(
                text("SELECT has_table_privilege(:r, :t, :p)"),
                {"r": role, "t": table, "p": privilege},
            ).scalar_one(), (role, table, privilege)
    for privilege in ("INSERT", "UPDATE", "DELETE", "TRUNCATE"):
        assert not db.execute(
            text("SELECT has_table_privilege('service_role', :t, :p)"),
            {"t": table, "p": privilege},
        ).scalar_one(), (table, privilege)
    policies = (
        db.execute(text("SELECT roles::text[] FROM pg_policies WHERE tablename = :t"), {"t": table})
        .scalars()
        .all()
    )
    assert all(set(r) <= {"api_role", "worker_role"} for r in policies)


def test_pending_primary_key_blocks_duplicate(role_engines, patient_schedule):
    patient, occ = patient_schedule
    sql, params = statements(patient, occ)[(PENDING, "INSERT")]
    with role_engines["worker_role"].connect() as c:
        tx = c.begin()
        try:
            c.execute(text(sql), params)
            with pytest.raises(IntegrityError, match="duplicate key"):
                c.execute(text(sql), params)
        finally:
            tx.rollback()


def test_foreign_keys_reject_unknown_user_and_schedule(db, patient_schedule):
    patient, occ = patient_schedule
    ghost = uuid4()
    with pytest.raises(IntegrityError, match="foreign key"):
        db.execute(
            text(f"INSERT INTO {CHECKPOINTS} (user_id, synced_at) VALUES (:u, now())"),
            {"u": ghost},
        )
    with pytest.raises(IntegrityError, match="foreign key"):
        db.execute(
            text(
                f"INSERT INTO {PENDING} (medication_schedule_id, scheduled_at, patient_user_id) "
                "VALUES (:s, :at, :u)"
            ),
            {"s": occ.schedule_id, "at": occ.scheduled_at, "u": ghost},
        )
    with pytest.raises(IntegrityError, match="foreign key"):
        db.execute(
            text(
                f"INSERT INTO {PENDING} (medication_schedule_id, scheduled_at, patient_user_id) "
                "VALUES (-1, :at, :u)"
            ),
            {"at": occ.scheduled_at, "u": patient},
        )


def test_not_null_columns(db, patient_schedule):
    patient, _ = patient_schedule
    with pytest.raises(IntegrityError, match="null value"):
        db.execute(
            text(f"INSERT INTO {CHECKPOINTS} (user_id, synced_at) VALUES (:u, NULL)"),
            {"u": patient},
        )
