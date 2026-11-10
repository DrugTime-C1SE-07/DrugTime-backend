from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError


@pytest.fixture
def conn(admin_engine):
    with admin_engine.execution_options(isolation_level="READ COMMITTED").connect() as connection:
        tx = connection.begin()
        try:
            yield connection
        finally:
            tx.rollback()


def test_new_scope_and_request_operation_accepted__AC10_AC11_AC12(conn, make):
    actor, patient = make.user(), make.user()
    scopes = (
        conn.execute(text("SELECT unnest(enum_range(NULL::access_data_scope))::text"))
        .scalars()
        .all()
    )
    assert set(scopes) == {
        "ho_so_suc_khoe",
        "danh_sach_thuoc",
        "lich_su_tuan_thu",
        "canh_bao_tuong_tac",
        "goi_y_bua_an",
        "danh_sach_benh_nhan_lien_ket",
    }
    for scope in scopes:
        conn.execute(
            text(
                "INSERT INTO access_logs "
                "(actor_user_id,actor_role,patient_user_id,data_scope,result) "
                "VALUES (:a,'family',:p,CAST(:s AS access_data_scope),'allowed')"
            ),
            {"a": actor, "p": patient, "s": scope},
        )
    for result, reason in (("allowed", None), ("denied", "khong_co_quyen")):
        conn.execute(
            text(
                "INSERT INTO family_link_audit_events(actor_user_id,operation,result,reason) "
                "VALUES (:a,'list_linked_patients',:r,:reason)"
            ),
            {"a": actor, "r": result, "reason": reason},
        )


def test_old_constraints_and_records_preserved_after_upgrade__AC12(conn, make):
    actor = make.user()
    # Isolate the old-schema fixture: never delete or downgrade append-only live logs.
    table = "migration_family_audit_linked"
    conn.execute(
        text(
            f"CREATE TEMP TABLE {table} "
            "(LIKE public.family_link_audit_events INCLUDING ALL) ON COMMIT DROP"
        )
    )
    conn.execute(
        text(
            f"INSERT INTO {table}(actor_user_id,patient_user_id,operation,result) "
            "VALUES (:a,:a,'list_caregivers','allowed')"
        ),
        {"a": actor},
    )
    # Rebuild only the prior CHECK definitions in this rollback-only test transaction,
    # then apply the exact new constraint migration against a table with old data.
    conn.execute(
        text(
            f"ALTER TABLE {table} "
            "DROP CONSTRAINT family_link_audit_events_operation_check, "
            "DROP CONSTRAINT family_link_audit_events_allowed_subject_check, "
            "DROP CONSTRAINT family_link_audit_events_allowed_link_check, "
            "DROP CONSTRAINT family_link_audit_events_list_subject_check"
        )
    )
    conn.execute(
        text(
            f"ALTER TABLE {table} "
            "ADD CONSTRAINT family_link_audit_events_operation_check "
            "CHECK(operation IN ('list_pending','approve','reject','list_caregivers',"
            "'enable_sharing','disable_sharing','revoke')), "
            "ADD CONSTRAINT family_link_audit_events_check1 "
            "CHECK(result<>'allowed' OR patient_user_id IS NOT NULL), "
            "ADD CONSTRAINT family_link_audit_events_allowed_link_check "
            "CHECK(result<>'allowed' OR operation IN ('list_pending','list_caregivers') "
            "OR link_id IS NOT NULL)"
        )
    )
    before = conn.execute(text(f"SELECT * FROM {table} ORDER BY id")).all()
    migration = next(
        (Path(__file__).parents[2] / "supabase/migrations").glob(
            "*_linked_patient_request_audit.sql"
        )
    ).read_text(encoding="utf-8")
    migration = migration.replace("public.family_link_audit_events", table)
    conn.exec_driver_sql(migration.replace("BEGIN;", "").replace("COMMIT;", ""))
    assert conn.execute(text(f"SELECT * FROM {table} ORDER BY id")).all() == before


@pytest.mark.parametrize(
    "role", ["postgres", "service_role", "api_role", "worker_role", "anon", "authenticated"]
)
@pytest.mark.parametrize("table", ["access_logs", "family_link_audit_events"])
@pytest.mark.parametrize("verb", ["UPDATE", "DELETE", "TRUNCATE"])
def test_audit_remains_append_only_for_all_roles__AC13(conn, make, role, table, verb):
    actor, patient = make.user(), make.user()
    conn.execute(
        text(
            "INSERT INTO access_logs(actor_user_id,actor_role,patient_user_id,"
            "data_scope,result) VALUES (:a,'family',:p,"
            "'danh_sach_benh_nhan_lien_ket','allowed')"
        ),
        {"a": actor, "p": patient},
    )
    conn.execute(
        text(
            "INSERT INTO family_link_audit_events(actor_user_id,operation,result) "
            "VALUES (:a,'list_linked_patients','allowed')"
        ),
        {"a": actor},
    )
    statement = {
        "UPDATE": f"UPDATE {table} SET id=id",
        "DELETE": f"DELETE FROM {table}",
        "TRUNCATE": f"TRUNCATE {table}",
    }[verb]
    with pytest.raises(DBAPIError), conn.begin_nested():
        conn.execute(text(f"SET LOCAL ROLE {role}"))
        conn.execute(text(statement))


@pytest.mark.parametrize(
    "operation,subject,link,result,reason",
    [
        ("list_linked_patients", True, None, "allowed", None),
        ("list_linked_patients", False, 42, "allowed", None),
        ("list_caregivers", False, None, "allowed", None),
        ("approve", True, None, "allowed", None),
        ("unknown", False, None, "denied", "khong_co_quyen"),
        ("list_linked_patients", False, None, "allowed", "khong_co_quyen"),
    ],
)
def test_request_subject_constraints__AC11_AC12(
    conn, make, operation, subject, link, result, reason
):
    actor = make.user()
    with pytest.raises(DBAPIError), conn.begin_nested():
        conn.execute(
            text(
                "INSERT INTO family_link_audit_events(actor_user_id,patient_user_id,"
                "link_id,operation,result,reason) VALUES (:a,:p,:l,:op,:r,:reason)"
            ),
            {
                "a": actor,
                "p": actor if subject else None,
                "l": link,
                "op": operation,
                "r": result,
                "reason": reason,
            },
        )


def test_minimal_grants_and_request_subject_constraints__AC13(conn):
    assert conn.execute(
        text("SELECT has_table_privilege('api_role','family_link_audit_events','INSERT')")
    ).scalar_one()
    for role in ("anon", "authenticated", "worker_role"):
        assert not conn.execute(
            text("SELECT has_table_privilege(:r,'family_link_audit_events','INSERT')"), {"r": role}
        ).scalar_one()
    for table in ("access_logs", "family_link_audit_events"):
        assert conn.execute(
            text("SELECT relrowsecurity FROM pg_class WHERE oid=CAST(:t AS regclass)"), {"t": table}
        ).scalar_one()
