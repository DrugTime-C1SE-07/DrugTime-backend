"""Migration 20261016083732_caregiver_links_reopenable_pairs và 20261016083734_link_request_attempts
(task 3.13, wf-db-migration): ràng buộc cặp một phần, client_uuid, grant theo role, eraser.

Áp migration lên dữ liệu có sẵn (4 cặp pending/active/revoked/rejected theo schema cũ) đã kiểm ở
giai đoạn implement: work/3.13-backend-post-links/evidence/implement-migration-existing-data.log.
"""

from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from drugtime.modules.family.domain.link_code import generate_code
from drugtime.shared.db import SqlUnitOfWork


def _insert_link(db, patient, family, status, client_uuid=None):
    db.execute(
        text(
            "INSERT INTO caregiver_links (patient_user_id, family_user_id, status, client_uuid, "
            "revoked_at, rejected_at) VALUES (:p, :f, CAST(:s AS link_status), :k, "
            "CASE WHEN :s = 'revoked' THEN now() END, CASE WHEN :s = 'rejected' THEN now() END)"
        ),
        {"p": patient, "f": family, "s": status, "k": client_uuid},
    )


def _statuses(db, patient, family):
    return (
        db.execute(
            text(
                "SELECT status::text FROM caregiver_links "
                "WHERE patient_user_id = :p AND family_user_id = :f ORDER BY id"
            ),
            {"p": patient, "f": family},
        )
        .scalars()
        .all()
    )


def _insert_attempt(db, family, client_uuid=None):
    db.execute(
        text("INSERT INTO link_request_attempts (family_user_id, client_uuid) VALUES (:f, :k)"),
        {"f": family, "k": client_uuid or uuid4()},
    )


def _attempt_count(db, family):
    return db.execute(
        text("SELECT count(*) FROM link_request_attempts WHERE family_user_id = :f"),
        {"f": family},
    ).scalar_one()


# --- caregiver_links (AC22, AC29) ---------------------------------------------------------------


def test_caregiver_links_schema_after_migration__AC22(db):
    constraints = (
        db.execute(
            text(
                "SELECT conname FROM pg_constraint "
                "WHERE conrelid = 'public.caregiver_links'::regclass AND contype = 'u'"
            )
        )
        .scalars()
        .all()
    )
    assert constraints == []  # UNIQUE (patient_user_id, family_user_id) đã bỏ
    indexes = dict(
        db.execute(
            text("SELECT indexname, indexdef FROM pg_indexes WHERE tablename = 'caregiver_links'")
        ).all()
    )
    assert (
        "WHERE (status = ANY (ARRAY['pending'::link_status, 'active'::link_status]))"
        in (indexes["caregiver_links_one_open_pair_idx"])
    )
    assert "UNIQUE" in indexes["caregiver_links_one_open_pair_idx"]
    assert "WHERE (client_uuid IS NOT NULL)" in indexes["caregiver_links_family_client_uuid_idx"]
    assert "UNIQUE" in indexes["caregiver_links_family_client_uuid_idx"]
    assert {"caregiver_links_pair_idx", "caregiver_links_family_linked_at_idx"} <= set(indexes)
    nullable = db.execute(
        text(
            "SELECT is_nullable FROM information_schema.columns "
            "WHERE table_name = 'caregiver_links' AND column_name = 'client_uuid'"
        )
    ).scalar_one()
    assert nullable == "YES"


@pytest.mark.parametrize(
    "first, second",
    [("pending", "pending"), ("pending", "active"), ("active", "pending"), ("active", "active")],
)
def test_open_pair_unique__AC22(db, make, first, second):
    patient, family = make.user(), make.user()
    _insert_link(db, patient, family, first)

    with pytest.raises(DBAPIError) as exc:
        _insert_link(db, patient, family, second)

    assert "caregiver_links_one_open_pair_idx" in str(exc.value)
    assert _statuses(db, patient, family) == [first]


def test_many_closed_rows_allowed__AC22(db, make):
    patient, family = make.user(), make.user()
    history = ["rejected", "rejected", "revoked", "revoked", "rejected", "pending"]

    for status in history:
        _insert_link(db, patient, family, status)

    assert _statuses(db, patient, family) == history


def test_client_uuid_unique_per_family__AC22(db, make):
    p1, p2, f1, f2 = make.user(), make.user(), make.user(), make.user()
    key = uuid4()
    _insert_link(db, p1, f1, "rejected", key)

    with pytest.raises(DBAPIError) as exc:
        _insert_link(db, p2, f1, "pending", key)

    assert "caregiver_links_family_client_uuid_idx" in str(exc.value)
    _insert_link(db, p1, f2, "pending", key)  # client_uuid chỉ có nghĩa trong một tài khoản
    _insert_link(db, p2, f1, "pending", None)
    _insert_link(db, p2, f2, "pending", None)


# --- link_request_attempts (AC18, AC23) ---------------------------------------------------------


def test_attempts_have_no_code_column__AC18(db):
    cols = (
        db.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = 'public' AND table_name = 'link_request_attempts' "
                "ORDER BY ordinal_position"
            )
        )
        .scalars()
        .all()
    )
    assert cols == ["id", "family_user_id", "client_uuid", "attempted_at", "account_locked_until"]


def test_wrong_codes_not_stored__AC18(client, db, make, auth):
    family = make.user()
    wrong = [generate_code() for _ in range(3)]
    for code in wrong:
        body = {"client_uuid": str(uuid4()), "code": code}
        assert (
            client.post("/family/link-requests", json=body, headers=auth(family)).status_code == 404
        )

    rows = db.execute(
        text("SELECT CAST(a AS text) FROM link_request_attempts a WHERE family_user_id = :f"),
        {"f": family},
    ).scalars()
    dump = "\n".join(rows)
    assert dump.count(str(family)) == 3
    for code in wrong:
        assert code not in dump and code.lower() not in dump


def test_locked_until_must_follow_attempt__AC23(db, make):
    family = make.user()

    with pytest.raises(DBAPIError) as exc:
        db.execute(
            text(
                "INSERT INTO link_request_attempts (family_user_id, client_uuid, attempted_at, "
                "account_locked_until) VALUES (:f, :k, now(), now() - interval '1 second')"
            ),
            {"f": family, "k": uuid4()},
        )

    assert "link_request_attempts_locked_after_attempt_check" in str(exc.value)


GRANTS = {
    "api_role": {"select": True, "insert": True, "update": False, "delete": False},
    "worker_role": {"select": True, "insert": False, "update": False, "delete": True},
}


@pytest.mark.parametrize(
    "role, action", [(r, a) for r in GRANTS for a in ("select", "insert", "update", "delete")]
)
def test_role_grants_on_attempts__AC23(role_engines, db, make, role, action):
    """Mỗi thao tác chạy trong transaction riêng rồi rollback."""
    family = make.user()
    _insert_attempt(db, family)
    sql = {
        "select": "SELECT client_uuid FROM link_request_attempts WHERE family_user_id = :f",
        "insert": "INSERT INTO link_request_attempts (family_user_id, client_uuid) VALUES (:f, :k)",
        "update": "UPDATE link_request_attempts SET account_locked_until = NULL "
        "WHERE family_user_id = :f",
        "delete": "DELETE FROM link_request_attempts WHERE family_user_id = :f",
    }[action]

    with role_engines[role].connect() as c:
        tx = c.begin()
        try:
            if GRANTS[role][action]:
                result = c.execute(text(sql), {"f": family, "k": uuid4()})
                if action in ("select", "delete"):
                    assert result.rowcount == 1  # RLS không chặn role được cấp
            else:
                with pytest.raises(DBAPIError) as exc:
                    c.execute(text(sql), {"f": family, "k": uuid4()})
                assert "permission denied" in str(exc.value)
        finally:
            tx.rollback()

    assert _attempt_count(db, family) == 1


def test_anon_authenticated_no_access__AC23(db):
    assert db.execute(
        text(
            "SELECT relrowsecurity FROM pg_class "
            "WHERE oid = 'public.link_request_attempts'::regclass"
        )
    ).scalar_one()
    for role in ("anon", "authenticated"):
        for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE"):
            assert not db.execute(
                text("SELECT has_table_privilege(:r, 'public.link_request_attempts', :p)"),
                {"r": role, "p": privilege},
            ).scalar_one(), (role, privilege)
    for privilege in ("INSERT", "UPDATE", "DELETE", "TRUNCATE"):
        assert not db.execute(
            text("SELECT has_table_privilege('service_role', 'public.link_request_attempts', :p)"),
            {"p": privilege},
        ).scalar_one(), privilege
    policy_roles = (
        db.execute(
            text(
                "SELECT unnest(roles)::text FROM pg_policies "
                "WHERE tablename = 'link_request_attempts' ORDER BY 1"
            )
        )
        .scalars()
        .all()
    )
    assert policy_roles == ["api_role", "worker_role"]


# --- Xóa dữ liệu user (AC19) --------------------------------------------------------------------


def test_erase_user_deletes_attempts_and_links__AC19(role_engines, db, make):
    from drugtime.modules.family import api as family_api

    family, other, patient = make.user(), make.user(), make.user()
    for _ in range(2):
        _insert_attempt(db, family)
    _insert_attempt(db, other)
    _insert_link(db, patient, family, "pending")
    _insert_link(db, patient, other, "pending")
    _insert_link(db, family, other, "active")  # F cũng là người bệnh của người khác

    # Worker chạy eraser bằng worker_role (runtime/job_runner.py).
    with role_engines["worker_role"].begin() as c:
        family_api.eraser.erase_user(SqlUnitOfWork(c), family)

    assert _attempt_count(db, family) == 0
    assert (
        db.execute(
            text(
                "SELECT count(*) FROM caregiver_links "
                "WHERE patient_user_id = :u OR family_user_id = :u"
            ),
            {"u": family},
        ).scalar_one()
        == 0
    )
    assert _attempt_count(db, other) == 1
    assert _statuses(db, patient, other) == ["pending"]
