"""Kiểm tra migration, RLS, grant, append-only và toàn vẹn dữ liệu cho task 3.16.

Bao phủ kịch bản I9 và I13 theo AC2, AC5, AC9, AC11, AC18.
"""


import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

# ==============================================================================
# I9: Legacy preserved and link deletion not blocked (AC11)
# ==============================================================================


def test_legacy_links_preserved_without_backfill__AC11(db, make):
    """AC11: Migration không tự động backfill evidence cho link cũ;

    dữ liệu link legacy vẫn được giữ nguyên vẹn.
    """
    patient = make.user(consents=("family_sharing",))
    family = make.user()

    # Tạo link active legacy (không có evidence)
    link_id = make.link(patient, family, status="active", legacy=True)

    # Khẳng định link tồn tại
    row = db.execute(
        text("SELECT status, sharing_enabled FROM caregiver_links WHERE id = :id"),
        {"id": link_id},
    ).one()
    assert row.status == "active"

    # Không có bằng chứng confirmation tự sinh
    confirmations = make.consent_confirmations(link_id)
    assert len(confirmations) == 0


def test_link_deletion_does_not_cascade_or_break_audit__AC11(admin_engine, make):
    """AC11: Xóa caregiver_links (quyền xóa dữ liệu người dùng / tombstone)

    không bị chặn bởi FK và không làm mất bằng chứng audit/confirmation lịch sử.
    """
    patient = make.user(consents=("family_sharing",))
    family = make.user()
    link_id = make.link(patient, family, status="active")

    # Đã có confirmation gắn với link_id
    assert len(make.consent_confirmations(link_id)) == 1

    with admin_engine.execution_options(isolation_level="READ COMMITTED").connect() as conn:
        tx = conn.begin()
        try:
            # Thêm 1 audit event gắn với link_id
            conn.execute(
                text(
                    "INSERT INTO family_link_audit_events "
                    "(actor_user_id, patient_user_id, link_id, operation, result) "
                    "VALUES (:a, :p, :l, 'approve', 'allowed')"
                ),
                {"a": patient, "p": patient, "l": link_id},
            )

            # Xóa link khỏi caregiver_links (như luồng erasure)
            conn.execute(text("DELETE FROM caregiver_links WHERE id = :id"), {"id": link_id})

            # Confirmation và audit vẫn còn nguyên vẹn, không bị cascade delete
            c_count = conn.execute(
                text("SELECT count(*) FROM family_link_consent_confirmations WHERE link_id = :l"),
                {"l": link_id},
            ).scalar_one()
            assert c_count == 1

            a_count = conn.execute(
                text("SELECT count(*) FROM family_link_audit_events WHERE link_id = :l"),
                {"l": link_id},
            ).scalar_one()
            assert a_count == 1
        finally:
            tx.rollback()


# ==============================================================================
# I13: RLS, grants, append-only triggers and integrity constraints (AC2, 5, 9, 11, 18)
# ==============================================================================


@pytest.mark.parametrize(
    "table", ["family_link_consent_confirmations", "family_link_audit_events"]
)
def test_rls_enabled_on_new_tables__AC18(db, table):
    """AC18: Bật RLS trên hai bảng mới."""
    is_rls = db.execute(
        text(f"SELECT relrowsecurity FROM pg_class WHERE oid = 'public.{table}'::regclass")
    ).scalar_one()
    assert is_rls is True


@pytest.mark.parametrize(
    "table", ["family_link_consent_confirmations", "family_link_audit_events"]
)
@pytest.mark.parametrize(
    "role", ["anon", "authenticated", "service_role", "api_role", "worker_role"]
)
@pytest.mark.parametrize("privilege", ["UPDATE", "DELETE", "TRUNCATE"])
def test_grants_disallow_mutations__AC18(db, table, role, privilege):
    """AC18: Quyền sửa/xóa/truncate bị thu hồi hoàn toàn khỏi mọi role."""
    has_priv = db.execute(
        text("SELECT has_table_privilege(:r, :t, :p)"),
        {"r": role, "t": f"public.{table}", "p": privilege},
    ).scalar_one()
    assert not has_priv


def test_api_role_has_select_and_insert__AC18(db):
    """AC18: api_role có quyền SELECT và INSERT trên cả hai bảng để phục vụ use case."""
    for table in ("family_link_consent_confirmations", "family_link_audit_events"):
        for priv in ("SELECT", "INSERT"):
            assert db.execute(
                text("SELECT has_table_privilege('api_role', :t, :p)"),
                {"t": f"public.{table}", "p": priv},
            ).scalar_one()


@pytest.mark.parametrize("role", ["anon", "authenticated"])
@pytest.mark.parametrize(
    "table", ["family_link_consent_confirmations", "family_link_audit_events"]
)
def test_client_roles_cannot_select_link_metadata__AC18(admin_engine, role, table):
    """Thực thi SELECT dưới role client bị từ chối bởi privilege PostgreSQL."""
    with admin_engine.connect() as conn:
        tx = conn.begin()
        try:
            conn.execute(text(f"SET LOCAL ROLE {role}"))
            with pytest.raises(DBAPIError):
                with conn.begin_nested():
                    conn.execute(text(f"SELECT * FROM public.{table} LIMIT 1"))
        finally:
            tx.rollback()


def test_worker_role_privileges_restricted__AC18(db):
    """AC18: worker_role chỉ được SELECT evidence; không có quyền ghi hay đọc audit."""
    # Worker được SELECT evidence
    assert db.execute(
        text(
            "SELECT has_table_privilege "
            "('worker_role', 'public.family_link_consent_confirmations', 'SELECT')"
        )
    ).scalar_one()
    # Worker KHÔNG được INSERT evidence
    assert not db.execute(
        text(
            "SELECT has_table_privilege "
            "('worker_role', 'public.family_link_consent_confirmations', 'INSERT')"
        )
    ).scalar_one()
    # Worker KHÔNG có bất kỳ quyền nào trên audit events
    for priv in ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE"):
        assert not db.execute(
            text(
                "SELECT has_table_privilege "
                "('worker_role', 'public.family_link_audit_events', :p)"
            ),
            {"p": priv},
        ).scalar_one()


@pytest.mark.parametrize(
    "role", ["postgres", "anon", "authenticated", "service_role", "api_role", "worker_role"]
)
@pytest.mark.parametrize("operation", ["UPDATE", "DELETE", "TRUNCATE"])
def test_append_only_triggers_block_all_roles__AC18(admin_engine, make, role, operation):
    """AC18: Trigger append-only và no_truncate chặn UPDATE/DELETE/TRUNCATE

    trên cả hai bảng mới đối với mọi role, kể cả postgres/owner.
    """
    p, f = make.user(consents=("family_sharing",)), make.user()
    link_id = make.link(p, f, status="active")

    with admin_engine.execution_options(isolation_level="READ COMMITTED").connect() as conn:
        tx = conn.begin()
        try:
            conn.execute(
                text(
                    "INSERT INTO family_link_audit_events "
                    "(actor_user_id, patient_user_id, link_id, operation, result) "
                    "VALUES (:a, :p, :l, 'approve', 'allowed')"
                ),
                {"a": p, "p": p, "l": link_id},
            )

            if role in {"api_role", "worker_role"}:
                conn.execute(text(f"GRANT {role} TO postgres"))
            conn.execute(text(f"SET LOCAL ROLE {role}"))

            for tbl in ("family_link_consent_confirmations", "family_link_audit_events"):
                stmts = {
                    "UPDATE": f"UPDATE {tbl} SET id = id",
                    "DELETE": f"DELETE FROM {tbl}",
                    "TRUNCATE": f"TRUNCATE {tbl}",
                }
                with pytest.raises(DBAPIError):
                    with conn.begin_nested():
                        conn.execute(text(stmts[operation]))
        finally:
            tx.rollback()


def test_integrity_constraints_on_confirmation__AC2_AC5_AC9(admin_engine, make):
    """AC2, AC5, AC9: Ràng buộc UNIQUE link_id, patient <> family, purpose, version."""
    p, f = make.user(consents=("family_sharing",)), make.user()
    link_id = make.link(p, f, status="active")

    with admin_engine.execution_options(isolation_level="READ COMMITTED").connect() as conn:
        tx = conn.begin()
        try:
            # 1. Trùng link_id -> vi phạm UNIQUE
            with pytest.raises(DBAPIError):
                with conn.begin_nested():
                    conn.execute(
                        text(
                            "INSERT INTO family_link_consent_confirmations "
                            "(link_id, patient_user_id, family_user_id, purpose, document_version) "
                            "VALUES (:l, :p, :f, 'family_sharing', 'v2')"
                        ),
                        {"l": link_id, "p": p, "f": f},
                    )

            # 2. patient_user_id == family_user_id -> vi phạm CHECK
            link_id2 = conn.execute(
                text(
                    "INSERT INTO caregiver_links (patient_user_id, family_user_id, status) "
                    "VALUES (:p, :f, 'pending') RETURNING id"
                ),
                {"p": p, "f": make.user()},
            ).scalar_one()
            with pytest.raises(DBAPIError):
                with conn.begin_nested():
                    conn.execute(
                        text(
                            "INSERT INTO family_link_consent_confirmations "
                            "(link_id, patient_user_id, family_user_id, purpose, document_version) "
                            "VALUES (:l, :p, :p, 'family_sharing', 'v1')"
                        ),
                        {"l": link_id2, "p": p},
                    )

            # 3. purpose sai -> vi phạm CHECK
            with pytest.raises(DBAPIError):
                with conn.begin_nested():
                    conn.execute(
                        text(
                            "INSERT INTO family_link_consent_confirmations "
                            "(link_id, patient_user_id, family_user_id, purpose, document_version) "
                            "VALUES (:l, :p, :f, 'wrong_purpose', 'v1')"
                        ),
                        {"l": link_id2, "p": p, "f": f},
                    )

            # 4. document_version rỗng -> vi phạm CHECK
            with pytest.raises(DBAPIError):
                with conn.begin_nested():
                    conn.execute(
                        text(
                            "INSERT INTO family_link_consent_confirmations "
                            "(link_id, patient_user_id, family_user_id, purpose, document_version) "
                            "VALUES (:l, :p, :f, 'family_sharing', '')"
                        ),
                        {"l": link_id2, "p": p, "f": f},
                    )
        finally:
            tx.rollback()


def test_integrity_constraints_on_audit_events__AC18(admin_engine, make):
    """AC18: Ràng buộc operation, result, snapshot của audit events."""
    p = make.user()
    with admin_engine.execution_options(isolation_level="READ COMMITTED").connect() as conn:
        tx = conn.begin()
        try:
            # 1. Operation không hợp lệ
            with pytest.raises(DBAPIError):
                with conn.begin_nested():
                    conn.execute(
                        text(
                            "INSERT INTO family_link_audit_events "
                            "(actor_user_id, patient_user_id, operation, result) "
                            "VALUES (:a, :p, 'invalid_op', 'allowed')"
                        ),
                        {"a": p, "p": p},
                    )

            # 2. Result không hợp lệ
            with pytest.raises(DBAPIError):
                with conn.begin_nested():
                    conn.execute(
                        text(
                            "INSERT INTO family_link_audit_events "
                            "(actor_user_id, patient_user_id, operation, result) "
                            "VALUES (:a, :p, 'approve', 'invalid_res')"
                        ),
                        {"a": p, "p": p},
                    )
        finally:
            tx.rollback()
