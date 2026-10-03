"""Migration 20261002101031_user_medications_soft_delete và 20261002101033_catalog_search_unaccent
(task adhoc-20261002-mobile-medication-api-integration; wf-db-migration).
"""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError


@pytest.fixture
def api_conn():
    """Kết nối của app (api_role, xem fixture app_settings trong conftest)."""
    from drugtime.shared.db import get_engine

    with get_engine().connect() as c:
        yield c


def test_deleted_at_column_nullable_timestamptz(db):
    row = db.execute(
        text(
            "SELECT data_type, is_nullable FROM information_schema.columns "
            "WHERE table_name = 'user_medications' AND column_name = 'deleted_at'"
        )
    ).one()
    assert row.data_type == "timestamp with time zone" and row.is_nullable == "YES"


def test_list_and_search_indexes_exist(db):
    defs = dict(
        db.execute(
            text(
                "SELECT indexname, indexdef FROM pg_indexes WHERE indexname IN ("
                "'user_medications_user_active_idx', 'medications_name_search_idx', "
                "'medications_ingredient_search_idx')"
            )
        ).all()
    )
    assert "WHERE (deleted_at IS NULL)" in defs["user_medications_user_active_idx"]
    assert "gin_trgm_ops" in defs["medications_name_search_idx"]
    assert "catalog_search_key(raw_active_ingredient)" in defs["medications_ingredient_search_idx"]


def test_extensions_in_extensions_schema(db):
    rows = dict(
        db.execute(
            text(
                "SELECT extname, extnamespace::regnamespace::text FROM pg_extension "
                "WHERE extname IN ('unaccent', 'pg_trgm')"
            )
        ).all()
    )
    assert rows == {"unaccent": "extensions", "pg_trgm": "extensions"}


@pytest.mark.parametrize(
    "raw, key",
    [
        ("Đồng Sulfat", "dong sulfat"),
        ("THUỐC HO Bảo Thanh", "thuoc ho bao thanh"),
        ("Amlodipin 5mg", "amlodipin 5mg"),
        ("100% a_b", "100% a_b"),
    ],
)
def test_catalog_search_key_as_api_role(api_conn, raw, key):
    assert api_conn.execute(text("SELECT current_user")).scalar_one() == "api_role"
    assert (
        api_conn.execute(text("SELECT public.catalog_search_key(:t)"), {"t": raw}).scalar_one()
        == key
    )


def test_catalog_search_key_is_immutable_and_strict(db):
    row = db.execute(
        text(
            "SELECT provolatile, proisstrict FROM pg_proc "
            "WHERE oid = 'public.catalog_search_key(text)'::regprocedure"
        )
    ).one()
    assert row.provolatile == "i" and row.proisstrict is True
    assert db.execute(text("SELECT public.catalog_search_key(NULL)")).scalar_one() is None


@pytest.mark.parametrize("role", ["anon", "authenticated"])
def test_client_roles_cannot_execute_search_key(db, role):
    assert (
        db.execute(
            text("SELECT has_function_privilege(:r, 'public.catalog_search_key(text)', 'EXECUTE')"),
            {"r": role},
        ).scalar_one()
        is False
    )


def test_api_role_grants_on_user_medications_unchanged(db):
    privileges = {
        r.privilege_type
        for r in db.execute(
            text(
                "SELECT privilege_type FROM information_schema.role_table_grants "
                "WHERE grantee = 'api_role' AND table_name = 'user_medications'"
            )
        )
    }
    assert privileges == {"SELECT", "INSERT", "UPDATE", "DELETE"}


def test_api_role_still_cannot_delete_dose_logs(db):
    assert (
        db.execute(
            text("SELECT has_table_privilege('api_role', 'dose_logs', 'DELETE')")
        ).scalar_one()
        is False
    )


def test_anon_cannot_read_user_medications_deleted_at(admin_engine):
    with admin_engine.execution_options(isolation_level="READ COMMITTED").connect() as c:
        with c.begin():
            c.execute(text("SET LOCAL ROLE anon"))
            try:
                rows = c.execute(
                    text("SELECT count(*) FROM user_medications WHERE deleted_at IS NOT NULL")
                ).scalar_one()
            except DBAPIError as exc:
                assert "permission denied" in str(exc.orig)
            else:
                assert rows == 0  # RLS không có policy cho anon
