"""Migration 20261116070000_meal_suggestion_images (task 5.11: AC23).

Kiểm bằng catalog Postgres và bằng kết nối api_role / worker_role thật.
"""

from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, ProgrammingError

FN = "ai_meal_reserve_image(text, text)"


def priv(db, role, privilege, obj="meal_images"):
    return db.execute(text("SELECT has_table_privilege(:r, :o, :p)"),
                      {"r": role, "o": obj, "p": privilege}).scalar_one()


def fn_priv(db, role):
    return db.execute(text("SELECT has_function_privilege(:r, :f, 'EXECUTE')"),
                      {"r": role, "f": FN}).scalar_one()


def test_table_rls_and_grants__AC23(db):
    assert db.execute(text("SELECT relrowsecurity FROM pg_class WHERE relname = 'meal_images'")
                      ).scalar_one() is True
    assert priv(db, "api_role", "SELECT")
    for p in ("INSERT", "UPDATE", "DELETE"):
        assert not priv(db, "api_role", p), p
    assert priv(db, "worker_role", "SELECT") and priv(db, "worker_role", "UPDATE")
    for p in ("INSERT", "DELETE"):
        assert not priv(db, "worker_role", p), p
    for role in ("anon", "authenticated"):
        for p in ("SELECT", "INSERT", "UPDATE", "DELETE"):
            assert not priv(db, role, p), (role, p)


def test_reserve_function_definer_and_execute_grants__AC23(db):
    row = db.execute(text(
        "SELECT prosecdef, proconfig FROM pg_proc WHERE proname = 'ai_meal_reserve_image'"
    )).one()
    assert row.prosecdef is True
    assert any(c.startswith("search_path=") for c in row.proconfig)
    assert fn_priv(db, "api_role")
    for role in ("worker_role", "anon", "authenticated"):
        assert not fn_priv(db, role), role


def test_api_role_cannot_write_directly_but_can_reserve__AC23(role_engines):
    key = f"dish {uuid4().hex}"
    with role_engines["api_role"].connect() as c:
        with pytest.raises(ProgrammingError):
            c.execute(text("INSERT INTO meal_images (dish_key, image_query, status) "
                           "VALUES (:k, 'q', 'pending')"), {"k": key})
        c.rollback()
        with pytest.raises(ProgrammingError):
            c.execute(text("UPDATE meal_images SET status = 'failed'"))
        c.rollback()
        first = c.execute(text("SELECT * FROM ai_meal_reserve_image(:k, 'q')"), {"k": key}).one()
        second = c.execute(text("SELECT * FROM ai_meal_reserve_image(:k, 'q')"), {"k": key}).one()
        c.commit()
    assert (first.status, first.enqueue) == ("pending", True)
    assert (second.image_id, second.status, second.enqueue) == (first.image_id, "pending", False)


def test_worker_role_updates_but_cannot_insert_or_reserve__AC23(db, role_engines):
    key = f"dish {uuid4().hex}"
    image_id = db.execute(text("INSERT INTO meal_images (dish_key, image_query, status) "
                               "VALUES (:k, 'q', 'pending') RETURNING id"), {"k": key}).scalar_one()
    with role_engines["worker_role"].begin() as c:
        c.execute(text("UPDATE meal_images SET status = 'failed', updated_at = now() "
                       "WHERE id = :i"), {"i": image_id})
    with role_engines["worker_role"].connect() as c:
        with pytest.raises(ProgrammingError):
            c.execute(text("INSERT INTO meal_images (dish_key, image_query, status) "
                           "VALUES ('x', 'q', 'pending')"))
        c.rollback()
        with pytest.raises(ProgrammingError):
            c.execute(text("SELECT * FROM ai_meal_reserve_image('y', 'q')"))
        c.rollback()
    assert db.execute(text("SELECT status FROM meal_images WHERE id = :i"),
                      {"i": image_id}).scalar_one() == "failed"


@pytest.mark.parametrize(
    "sql",
    [
        "INSERT INTO meal_images (dish_key, image_query, status) VALUES (:k, 'q', 'done')",
        "INSERT INTO meal_images (dish_key, image_query, status) VALUES (:k, 'q', 'ready')",
        "INSERT INTO meal_images (dish_key, image_query, status) VALUES (:k, :long, 'pending')",
        "INSERT INTO meal_images (dish_key, image_query, status, content_type) "
        "VALUES (:k, 'q', 'pending', 'image/gif')",
        "INSERT INTO meal_images (dish_key, image_query, status, size_bytes) "
        "VALUES (:k, 'q', 'pending', 2097153)",
    ],
    ids=["status_lạ", "ready_thiếu_nguồn", "query_61", "gif", "quá_2MB"],
)
def test_check_constraints_reject_bad_rows__AC23(db, sql):
    with pytest.raises(IntegrityError):
        db.execute(text(sql), {"k": f"dish {uuid4().hex}", "long": "q" * 61})


def test_dish_key_unique__AC23(db):
    key = f"dish {uuid4().hex}"
    db.execute(text("INSERT INTO meal_images (dish_key, image_query, status) "
                    "VALUES (:k, 'q', 'pending')"), {"k": key})
    with pytest.raises(IntegrityError):
        db.execute(text("INSERT INTO meal_images (dish_key, image_query, status) "
                        "VALUES (:k, 'q2', 'pending')"), {"k": key})


def test_bucket_private_with_limits__AC23(db):
    row = db.execute(text("SELECT public, file_size_limit, allowed_mime_types "
                          "FROM storage.buckets WHERE id = 'meal-images'")).one()
    assert row.public is False and row.file_size_limit == 2097152
    assert sorted(row.allowed_mime_types) == ["image/jpeg", "image/png", "image/webp"]
    policies = db.execute(text(
        "SELECT count(*) FROM pg_policies WHERE schemaname = 'storage' "
        "AND tablename = 'objects' AND (qual LIKE '%meal-images%' "
        "OR with_check LIKE '%meal-images%')")).scalar_one()
    assert policies == 0  # client không có quyền nào trên bucket này


def test_previous_suggestion_column_nullable_set_null_and_erasure_works__AC23(
    db, make, role_engines
):
    col = db.execute(text(
        "SELECT is_nullable, column_default FROM information_schema.columns "
        "WHERE table_name = 'meal_suggestions' AND column_name = 'previous_suggestion_id'")).one()
    assert (col.is_nullable, col.column_default) == ("YES", None)
    fk = db.execute(text(
        "SELECT confdeltype FROM pg_constraint WHERE conrelid = 'meal_suggestions'::regclass "
        "AND contype = 'f' AND conkey = ARRAY[(SELECT attnum FROM pg_attribute WHERE "
        "attrelid = 'meal_suggestions'::regclass AND attname = 'previous_suggestion_id')]::int2[]"
    )).scalar_one()
    assert fk == "n"  # ON DELETE SET NULL

    p = make.user()
    first = db.execute(text("INSERT INTO meal_suggestions (user_id, suggestion_content) "
                            "VALUES (:u, '{}'::jsonb) RETURNING id"), {"u": p}).scalar_one()
    second = db.execute(text("INSERT INTO meal_suggestions (user_id, suggestion_content, "
                             "previous_suggestion_id) VALUES (:u, '{}'::jsonb, :f) RETURNING id"),
                        {"u": p, "f": first}).scalar_one()
    # Worker xóa dữ liệu người dùng (luồng erasure): chỉ có DELETE, FK SET NULL vẫn chạy.
    with role_engines["worker_role"].begin() as c:
        c.execute(text("DELETE FROM meal_suggestions WHERE id = :i"), {"i": first})
    assert db.execute(text("SELECT previous_suggestion_id FROM meal_suggestions WHERE id = :i"),
                      {"i": second}).scalar_one() is None
    with role_engines["worker_role"].begin() as c:
        c.execute(text("DELETE FROM meal_suggestions WHERE user_id = :u"), {"u": p})
