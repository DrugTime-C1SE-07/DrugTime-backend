"""Migration 20261021030401: audit của quản lý người giám sát (adhoc-20261020-family-link-approval).

Bao phủ AC14: operation mới được nhận, operation lạ vẫn bị từ chối, dòng `allowed` gắn link vẫn
bắt buộc `link_id`, và bảng vẫn chỉ ghi thêm với mọi role.
"""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

_INSERT = text(
    "INSERT INTO family_link_audit_events "
    "(actor_user_id, patient_user_id, link_id, operation, result, reason) "
    "VALUES (:a, :p, :l, :op, :result, :reason)"
)


@pytest.fixture
def conn(admin_engine):
    """Kết nối có transaction thật, luôn rollback: test không để lại dòng audit."""
    with admin_engine.execution_options(isolation_level="READ COMMITTED").connect() as c:
        tx = c.begin()
        try:
            yield c
        finally:
            tx.rollback()


def _insert(conn, actor, *, link_id, operation, result="allowed", reason=None):
    with conn.begin_nested():
        conn.execute(
            _INSERT,
            {
                "a": actor,
                "p": actor,
                "l": link_id,
                "op": operation,
                "result": result,
                "reason": reason,
            },
        )


@pytest.mark.parametrize("operation", ["enable_sharing", "disable_sharing", "revoke"])
def test_new_link_operations_accepted_allowed_and_denied__AC14(conn, make, operation):
    patient, family = make.user(consents=("family_sharing",)), make.user()
    link_id = make.link(patient, family, status="active")

    _insert(conn, patient, link_id=link_id, operation=operation)
    _insert(
        conn, family, link_id=link_id, operation=operation, result="denied", reason="khong_co_quyen"
    )


def test_list_caregivers_allowed_without_link_id__AC14(conn, make):
    _insert(conn, make.user(), link_id=None, operation="list_caregivers")


@pytest.mark.parametrize("operation", ["enable_sharing", "disable_sharing", "revoke", "approve"])
def test_link_scoped_allowed_requires_link_id__AC14(conn, make, operation):
    with pytest.raises(DBAPIError):
        _insert(conn, make.user(), link_id=None, operation=operation)


@pytest.mark.parametrize("operation", ["update_sharing", "delete", "LIST_CAREGIVERS", ""])
def test_unknown_operation_still_rejected__AC14(conn, make, operation):
    with pytest.raises(DBAPIError):
        _insert(conn, make.user(), link_id=None, operation=operation)


def test_enable_sharing_denied_with_consent_reason_accepted__AC14(conn, make):
    patient, family = make.user(consents=("family_sharing",)), make.user()
    link_id = make.link(patient, family, status="active")

    _insert(
        conn,
        patient,
        link_id=link_id,
        operation="enable_sharing",
        result="denied",
        reason="consent_revoked",
    )


@pytest.mark.parametrize(
    "role", ["postgres", "anon", "authenticated", "service_role", "api_role", "worker_role"]
)
@pytest.mark.parametrize("statement", ["UPDATE", "DELETE", "TRUNCATE"])
def test_still_append_only_for_every_role__AC14(conn, make, role, statement):
    patient, family = make.user(consents=("family_sharing",)), make.user()
    link_id = make.link(patient, family, status="active")
    _insert(conn, patient, link_id=link_id, operation="revoke")

    if role in {"api_role", "worker_role"}:
        conn.execute(text(f"GRANT {role} TO postgres"))
    conn.execute(text(f"SET LOCAL ROLE {role}"))
    sql = {
        "UPDATE": "UPDATE family_link_audit_events SET operation = 'approve'",
        "DELETE": "DELETE FROM family_link_audit_events",
        "TRUNCATE": "TRUNCATE family_link_audit_events",
    }[statement]
    with pytest.raises(DBAPIError):
        with conn.begin_nested():
            conn.execute(text(sql))


def test_constraint_definitions_match_migration__AC14(db):
    rows = dict(
        db.execute(
            text(
                "SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint "
                "WHERE conrelid = 'public.family_link_audit_events'::regclass AND contype = 'c'"
            )
        ).all()
    )

    assert "family_link_audit_events_check2" not in rows
    operations = rows["family_link_audit_events_operation_check"]
    for op in (
        "list_pending",
        "approve",
        "reject",
        "list_caregivers",
        "enable_sharing",
        "disable_sharing",
        "revoke",
    ):
        assert f"'{op}'::text" in operations
    allowed = rows["family_link_audit_events_allowed_link_check"]
    assert "'list_pending'::text" in allowed and "'list_caregivers'::text" in allowed
    assert "link_id IS NOT NULL" in allowed
