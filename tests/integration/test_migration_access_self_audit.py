from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError


def test_self_role_constraints_and_existing_logs_preserved__AC18(admin_engine, make):
    owner, family = make.user(), make.user()
    insert = text(
        "INSERT INTO access_logs (actor_user_id,actor_role,patient_user_id,data_scope,result) "
        "VALUES (:a,CAST(:r AS access_actor_role),:p,'ho_so_suc_khoe',:v)"
    )
    with admin_engine.execution_options(isolation_level="READ COMMITTED").connect() as conn:
        tx = conn.begin()
        try:
            conn.execute(insert, {"a": owner, "r": "patient", "p": owner, "v": "allowed"})
            conn.execute(insert, {"a": owner, "r": "patient", "p": owner, "v": "denied"})
            conn.execute(insert, {"a": family, "r": "family", "p": owner, "v": "allowed"})
            for actor, role, result in (
                (family, "patient", "allowed"),
                (owner, "family", "allowed"),
                (family, "khong_co_quyen", "allowed"),
            ):
                with pytest.raises(DBAPIError):
                    with conn.begin_nested():
                        conn.execute(insert, {"a": actor, "r": role, "p": owner, "v": result})
            conn.execute(text("DROP TRIGGER access_logs_append_only ON access_logs"))
            conn.execute(text("DROP TRIGGER access_logs_no_truncate ON access_logs"))
            conn.execute(text("DROP FUNCTION public.forbid_access_log_mutation()"))
            conn.execute(text("DELETE FROM access_logs WHERE actor_user_id=patient_user_id"))
            conn.execute(
                text("ALTER TABLE access_logs DROP CONSTRAINT access_logs_actor_identity_check")
            )
            conn.execute(
                text("ALTER TABLE access_logs DROP CONSTRAINT access_logs_allowed_role_check")
            )
            conn.execute(
                text(
                    "ALTER TABLE access_logs ADD CHECK (actor_user_id<>patient_user_id), "
                    "ADD CHECK (result='denied' OR actor_role IN ('family','admin'))"
                )
            )
            before = conn.execute(text("SELECT * FROM access_logs ORDER BY id")).all()
            path = (
                Path(__file__).resolve().parents[2]
                / "supabase/migrations/20261013022744_access_logs_self_audit.sql"
            )
            conn.connection.driver_connection.execute(path.read_text(encoding="utf-8"))
            assert conn.execute(text("SELECT * FROM access_logs ORDER BY id")).all() == before
            conn.execute(insert, {"a": owner, "r": "patient", "p": owner, "v": "allowed"})
        finally:
            tx.rollback()


@pytest.mark.parametrize(
    "role", ["postgres", "anon", "authenticated", "service_role", "api_role", "worker_role"]
)
@pytest.mark.parametrize("operation", ["UPDATE", "DELETE", "TRUNCATE"])
def test_access_logs_append_only_all_roles__AC14_AC18(admin_engine, make, role, operation):
    user = make.user()
    with admin_engine.execution_options(isolation_level="READ COMMITTED").connect() as conn:
        tx = conn.begin()
        try:
            conn.execute(
                text(
                    "INSERT INTO access_logs "
                    "(actor_user_id,actor_role,patient_user_id,data_scope,result) "
                    "VALUES (:u,'patient',:u,'ho_so_suc_khoe','allowed')"
                ),
                {"u": user},
            )
            if role in {"api_role", "worker_role"}:
                # Membership exists only inside this rollback-only test transaction.
                conn.execute(text(f"GRANT {role} TO postgres"))
            conn.execute(text(f"SET LOCAL ROLE {role}"))
            statements = {
                "UPDATE": "UPDATE access_logs SET rejection_reason='tampered'",
                "DELETE": "DELETE FROM access_logs",
                "TRUNCATE": "TRUNCATE access_logs",
            }
            with pytest.raises(DBAPIError):
                with conn.begin_nested():
                    conn.execute(text(statements[operation]))
        finally:
            tx.rollback()


def test_access_logs_rls_and_grants__AC18(db):
    assert db.execute(
        text("SELECT relrowsecurity FROM pg_class WHERE oid='public.access_logs'::regclass")
    ).scalar_one()
    for role in ("anon", "authenticated", "service_role", "api_role", "worker_role"):
        for privilege in ("UPDATE", "DELETE", "TRUNCATE"):
            assert not db.execute(
                text("SELECT has_table_privilege(:r,'public.access_logs',:p)"),
                {"r": role, "p": privilege},
            ).scalar_one()
    for privilege in ("SELECT", "INSERT"):
        assert db.execute(
            text("SELECT has_table_privilege('api_role','access_logs',:p)"), {"p": privilege}
        ).scalar_one()
    assert (
        db.execute(
            text(
                "SELECT count(*) FROM pg_policies WHERE tablename='access_logs' "
                "AND roles && ARRAY['anon','authenticated']::name[]"
            )
        ).scalar_one()
        == 0
    )
    for role in ("anon", "authenticated"):
        assert not db.execute(
            text("SELECT has_table_privilege(:r,'access_logs','SELECT')"), {"r": role}
        ).scalar_one()
    assert not db.execute(
        text(
            "SELECT EXISTS(SELECT 1 FROM information_schema.columns "
            "WHERE table_name='user_conditions' AND column_name='deleted_at')"
        )
    ).scalar_one()
