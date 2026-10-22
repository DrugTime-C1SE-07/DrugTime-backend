"""AC3/AC7: admin-self denied audit, actor identity and append-only on real PostgreSQL."""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError

INSERT = text(
    "INSERT INTO access_logs (actor_user_id,actor_role,patient_user_id,data_scope,result) "
    "VALUES (:a,:r,:p,'lich_su_tuan_thu',:result) RETURNING id"
)


@pytest.mark.parametrize(
    "same,role,result,accepted",
    [
        (True, "patient", "allowed", True),
        (True, "patient", "denied", True),
        (True, "family", "allowed", False),
        (True, "family", "denied", False),
        (True, "admin", "allowed", False),
        (True, "admin", "denied", True),
        (True, "khong_co_quyen", "allowed", False),
        (True, "khong_co_quyen", "denied", False),
        (False, "patient", "allowed", False),
        (False, "patient", "denied", False),
        (False, "family", "allowed", True),
        (False, "family", "denied", True),
        (False, "admin", "allowed", True),
        (False, "admin", "denied", True),
        (False, "khong_co_quyen", "allowed", False),
        (False, "khong_co_quyen", "denied", True),
    ],
)
def test_access_log_actor_identity_matrix__AC3_AC7(
    db, make, role_engines, same, role, result, accepted
):
    actor, other = make.user(), make.user()
    values = {"a": actor, "p": actor if same else other, "r": role, "result": result}
    with role_engines["api_role"].connect() as conn:
        tx = conn.begin()
        try:
            if accepted:
                assert conn.execute(INSERT, values).scalar_one() > 0
            else:
                with pytest.raises(IntegrityError) as error:
                    conn.execute(INSERT, values)
                assert error.value.orig.sqlstate == "23514"
        finally:
            tx.rollback()
    assert (
        db.execute(
            text("SELECT count(*) FROM access_logs WHERE actor_user_id=:a"), {"a": actor}
        ).scalar_one()
        == 0
    )


@pytest.mark.parametrize("role", ["api_role", "worker_role", "postgres"])
@pytest.mark.parametrize("operation", ["update", "delete", "truncate"])
def test_access_logs_remain_append_only_after_actor_identity_migration__AC7(
    db, make, admin_engine, role_engines, role, operation
):
    actor = make.user()
    log_id = db.execute(
        INSERT, {"a": actor, "p": actor, "r": "patient", "result": "allowed"}
    ).scalar_one()
    query = text("SELECT * FROM access_logs WHERE id=:id")
    before = db.execute(query, {"id": log_id}).one()
    statement = {
        "update": "UPDATE access_logs SET result='denied' WHERE id=:id",
        "delete": "DELETE FROM access_logs WHERE id=:id",
        "truncate": "TRUNCATE access_logs",
    }[operation]
    engine = (
        admin_engine.execution_options(isolation_level="READ COMMITTED")
        if role == "postgres"
        else role_engines[role]
    )
    with engine.connect() as conn:
        tx = conn.begin()
        try:
            with pytest.raises(DBAPIError) as error:
                conn.execute(text(statement), {"id": log_id})
            assert error.value.orig.sqlstate == ("P0001" if role == "postgres" else "42501")
        finally:
            tx.rollback()
    assert db.execute(query, {"id": log_id}).one() == before
