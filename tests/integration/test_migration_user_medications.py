"""Migration user_medications_dosing_stock_idempotency (task 2.01, AC20)."""

from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError


@pytest.fixture
def owner(make):
    """Người dùng có một đơn thuốc thủ công và một thuốc danh mục."""
    user = make.user()
    prescription = make.db.execute(
        text(
            "INSERT INTO prescriptions (user_id, entry_source) VALUES (:u, 'thu_cong') RETURNING id"
        ),
        {"u": user},
    ).scalar_one()
    return user, prescription, make.catalog_medication()


def _insert_old_style(db, user, prescription, drug, **extra):
    """Chèn như code trước migration: không có cột mới nào."""
    cols = ", ".join(extra)
    vals = ", ".join(f":{k}" for k in extra)
    return db.execute(
        text(
            "INSERT INTO user_medications (user_id, prescription_id, medication_id, "
            "entry_method, quantity_per_dose, doses_per_day"
            + (f", {cols}" if cols else "")
            + ") VALUES (:u, :p, :m, 'thu_cong', 1, 1"
            + (f", {vals}" if vals else "")
            + ") RETURNING id, dosing_mode::text AS mode, intake_timing, stock_quantity, "
            "client_uuid"
        ),
        {"u": user, "p": prescription, "m": drug, **extra},
    ).one()


def test_old_style_rows_default_to_scheduled_and_null_client_uuid(db, owner):
    a = _insert_old_style(db, *owner)
    b = _insert_old_style(db, *owner)  # nhiều client_uuid NULL không vi phạm UNIQUE
    for row in (a, b):
        assert row.mode == "theo_gio"
        assert row.intake_timing is None and row.stock_quantity is None
        assert row.client_uuid is None


def test_client_uuid_unique_per_user(db, make, owner):
    user, prescription, drug = owner
    key = uuid4()
    _insert_old_style(db, user, prescription, drug, client_uuid=key)
    with pytest.raises(IntegrityError, match="user_medications_client_uuid_uq"):
        _insert_old_style(db, user, prescription, drug, client_uuid=key)


@pytest.mark.parametrize("stock", [-1, 10000])
def test_stock_quantity_check(db, owner, stock):
    with pytest.raises(IntegrityError, match="stock_quantity"):
        _insert_old_style(db, *owner, stock_quantity=stock)


def test_enum_values(db, owner):
    with pytest.raises(DBAPIError):
        db.execute(text("SELECT CAST('daily' AS medication_dosing_mode)"))
    labels = db.execute(
        text(
            "SELECT t.typname, array_agg(e.enumlabel ORDER BY e.enumsortorder) AS labels "
            "FROM pg_type t JOIN pg_enum e ON e.enumtypid = t.oid "
            "WHERE t.typname IN ('medication_dosing_mode', 'medication_intake_timing') "
            "GROUP BY t.typname"
        )
    ).all()
    assert dict((r.typname, r.labels) for r in labels) == {
        "medication_dosing_mode": ["theo_gio", "khi_can"],
        "medication_intake_timing": ["truoc_an", "sau_an", "khong_lien_quan"],
    }


def test_one_default_prescription_per_user(db, make):
    user = make.user()
    insert = text("INSERT INTO prescriptions (user_id, entry_source) VALUES (:u, 'mac_dinh')")
    db.execute(insert, {"u": user})
    with pytest.raises(IntegrityError, match="prescriptions_one_default_per_user_uq"):
        db.execute(insert, {"u": user})
    # Đơn nhập tay/OCR không bị giới hạn.
    for _ in range(2):
        db.execute(
            text("INSERT INTO prescriptions (user_id, entry_source) VALUES (:u, 'thu_cong')"),
            {"u": user},
        )


def _privileges(db, role):
    return {
        priv
        for priv in ("SELECT", "INSERT", "UPDATE", "DELETE")
        if db.execute(
            text("SELECT has_table_privilege(:r, 'user_medications', :p)"),
            {"r": role, "p": priv},
        ).scalar_one()
    }


def test_grants_unchanged(db):
    assert _privileges(db, "api_role") == {"SELECT", "INSERT", "UPDATE", "DELETE"}
    assert _privileges(db, "worker_role") == {"SELECT", "DELETE"}
    for column in ("dosing_mode", "intake_timing", "stock_quantity", "client_uuid"):
        assert db.execute(
            text("SELECT has_column_privilege('api_role', 'user_medications', :c, 'UPDATE')"),
            {"c": column},
        ).scalar_one()


def test_anon_cannot_read(db, admin_engine, owner):
    _insert_old_style(db, *owner)
    with admin_engine.execution_options(isolation_level="READ COMMITTED").connect() as c:
        with c.begin():
            c.execute(text("SET LOCAL ROLE anon"))
            try:
                rows = c.execute(text("SELECT count(*) FROM user_medications")).scalar_one()
            except DBAPIError as exc:
                assert "permission denied" in str(exc.orig)
            else:
                assert rows == 0  # RLS không có policy cho anon

# --- pill appearance (adhoc-20261120-add-medication-ux, AC22) --------------------------------


def test_pill_columns_nullable_text_and_old_style_rows_null__AC22(db, owner):
    cols = db.execute(
        text(
            "SELECT column_name, data_type, is_nullable, column_default "
            "FROM information_schema.columns WHERE table_name = 'user_medications' "
            "AND column_name IN ('pill_shape', 'pill_color') ORDER BY column_name"
        )
    ).all()
    assert [tuple(c) for c in cols] == [
        ("pill_color", "text", "YES", None),
        ("pill_shape", "text", "YES", None),
    ]
    row = _insert_old_style(db, *owner)
    pill = db.execute(
        text("SELECT pill_shape, pill_color FROM user_medications WHERE id = :i"), {"i": row.id}
    ).one()
    assert tuple(pill) == (None, None)


@pytest.mark.parametrize(
    "column, value, constraint",
    [
        ("pill_shape", "hexagon", "user_medications_pill_shape_chk"),
        ("pill_shape", "Capsule", "user_medications_pill_shape_chk"),
        ("pill_color", "teal", "user_medications_pill_color_chk"),
    ],
)
def test_pill_check_rejects_unknown_values__AC22(db, owner, column, value, constraint):
    with pytest.raises(IntegrityError, match=constraint):
        _insert_old_style(db, *owner, **{column: value})
    row = _insert_old_style(db, *owner)
    with pytest.raises(IntegrityError, match=constraint):
        db.execute(
            text(f"UPDATE user_medications SET {column} = :v WHERE id = :i"),
            {"v": value, "i": row.id},
        )


def test_pill_check_accepts_every_contract_value__AC22(db, owner):
    shapes = [
        "capsule", "round_tablet", "oblong_tablet", "softgel", "effervescent",
        "powder_sachet", "syrup", "drops", "spray", "injection_pen", "topical",
    ]
    colors = [
        "white", "yellow", "orange", "pink", "red", "brown", "blue", "green", "purple", "gray",
    ]
    for shape, color in zip(shapes, colors + ["white"], strict=True):
        _insert_old_style(db, *owner, pill_shape=shape, pill_color=color)
