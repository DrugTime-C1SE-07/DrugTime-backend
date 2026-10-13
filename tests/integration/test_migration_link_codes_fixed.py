"""Migration 20261013040307_link_codes_one_fixed_code_per_user (task 3.10, wf-db-migration):
schema, ràng buộc, grant theo role và family.eraser trên schema mới."""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from drugtime.shared.db import SqlUnitOfWork


def _insert(db, user_id, code):
    db.execute(
        text("INSERT INTO link_codes (patient_user_id, code) VALUES (:u, :c)"),
        {"u": user_id, "c": code},
    )


def _codes(db, user_id):
    return (
        db.execute(text("SELECT code FROM link_codes WHERE patient_user_id = :u"), {"u": user_id})
        .scalars()
        .all()
    )


def _unique_code(prefix):
    from drugtime.modules.family.domain.link_code import generate_code

    return prefix + generate_code()[len(prefix) :]


def test_link_codes_columns_after_migration__AC11(db):
    cols = (
        db.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = 'public' AND table_name = 'link_codes' "
                "ORDER BY ordinal_position"
            )
        )
        .scalars()
        .all()
    )
    assert cols == ["id", "patient_user_id", "code", "created_at"]

    indexes = (
        db.execute(
            text("SELECT indexname FROM pg_indexes WHERE tablename = 'link_codes' ORDER BY 1")
        )
        .scalars()
        .all()
    )
    assert indexes == ["link_codes_code_key", "link_codes_patient_user_id_key", "link_codes_pkey"]


def test_second_code_for_same_user_rejected__AC11(db, make):
    user = make.user(consents=())
    _insert(db, user, _unique_code("A"))

    with pytest.raises(DBAPIError) as exc:
        _insert(db, user, _unique_code("B"))

    assert "link_codes_patient_user_id_key" in str(exc.value)
    assert len(_codes(db, user)) == 1


def test_duplicate_code_rejected__AC11(db, make):
    u, v = make.user(consents=()), make.user(consents=())
    code = _unique_code("C")
    _insert(db, u, code)

    with pytest.raises(DBAPIError) as exc:
        _insert(db, v, code)

    assert "link_codes_code_key" in str(exc.value)
    assert _codes(db, v) == []


@pytest.mark.parametrize(
    "code",
    ["LEGACYIO01", "abcdefghjk", "ABCDEFGHJ", "ABCDEFGHJKM"],
    ids=["ky-tu-de-nham", "chu-thuong", "9-ky-tu", "11-ky-tu"],
)
def test_code_format_check_rejects_invalid_code__AC11(db, make, code):
    """Review F1: DB giữ định dạng mã như contract, để không user nào kẹt với mã sai (500)."""
    user = make.user(consents=())

    with pytest.raises(DBAPIError) as exc:
        _insert(db, user, code)

    assert "link_codes_code_format_check" in str(exc.value)
    assert _codes(db, user) == []


GRANTS = {
    "api_role": {"select": True, "insert": True, "update": False, "delete": False},
    "worker_role": {"select": True, "insert": False, "update": False, "delete": True},
}


@pytest.mark.parametrize(
    "role, action", [(r, a) for r in GRANTS for a in ("select", "insert", "update", "delete")]
)
def test_role_grants_on_link_codes__AC13(role_engines, db, make, role, action):
    """Mỗi thao tác chạy trong transaction riêng rồi rollback."""
    user = make.user(consents=())
    existing = _unique_code("D")
    _insert(db, user, existing)
    other = make.user(consents=())
    sql = {
        "select": "SELECT code FROM link_codes WHERE patient_user_id = :u",
        "insert": "INSERT INTO link_codes (patient_user_id, code) VALUES (:o, :c)",
        "update": "UPDATE link_codes SET code = :c WHERE patient_user_id = :u",
        "delete": "DELETE FROM link_codes WHERE patient_user_id = :u",
    }[action]
    params = {"u": user, "o": other, "c": _unique_code("E")}

    with role_engines[role].connect() as c:
        tx = c.begin()
        try:
            if GRANTS[role][action]:
                c.execute(text(sql), params)
            else:
                with pytest.raises(DBAPIError) as exc:
                    c.execute(text(sql), params)
                assert "permission denied" in str(exc.value)
        finally:
            tx.rollback()

    assert _codes(db, user) == [existing]


def test_family_eraser_deletes_only_that_users_code__AC14(role_engines, db, make):
    from drugtime.modules.family import api as family

    u, v = make.user(consents=()), make.user(consents=())
    code_v = _unique_code("F")
    _insert(db, u, _unique_code("G"))
    _insert(db, v, code_v)

    # Worker chạy eraser bằng worker_role (runtime/job_runner.py).
    with role_engines["worker_role"].begin() as c:
        family.eraser.erase_user(SqlUnitOfWork(c), u)

    assert _codes(db, u) == []
    assert _codes(db, v) == [code_v]
