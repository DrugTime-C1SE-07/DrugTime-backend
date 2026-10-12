"""Migration interaction_rule_versions (task 2.16): phiên bản bất biến, grant tối thiểu, unique
chỉ tính phiên bản mở. AC22, AC24, AC25.

Backfill dữ liệu có trước migration được kiểm ở giai đoạn implement bằng cách áp migration lên dữ
liệu kiểu cũ (work/2.16-interaction-catalog-crud/evidence/impl-check-migration.log); ở đây kiểm
dòng chèn theo kiểu cũ (không có cột mới) vẫn thành phiên bản 1 hợp lệ.
"""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

DDI = "active_ingredient_interactions"
FOOD = "drug_food_interactions"
THRESHOLDS = "active_ingredient_interaction_dose_thresholds"


def _insert_ddi_sql(extra_cols: str = "", extra_vals: str = "") -> str:
    """INSERT theo kiểu trước migration: không có rule_id, version, created_by..."""
    return (
        f"INSERT INTO {DDI} (ingredient_a_id, ingredient_b_id, ingredient_b_in_table_a, "
        "interaction_type, severity_level, handling_type, description, source, "
        f"verification_status{extra_cols}) VALUES (:a, :b, 'co', 'phu_thuoc_lieu', 2, "
        f"'can_theo_doi', 'd', 's', 'da_xac_minh'{extra_vals}) RETURNING id"
    )


@pytest.fixture
def pair(make):
    return make.ingredient(), make.ingredient()


@pytest.fixture
def postgres_tx(admin_engine):
    """Kết nối postgres có giao dịch thật (fixture `db` là autocommit, `begin()` không mở giao
    dịch DB). Dùng khi cần nhiều câu cùng giao dịch, SET LOCAL ROLE, hoặc chắc chắn rollback."""
    return admin_engine.execution_options(isolation_level="READ COMMITTED")


@pytest.fixture
def rule(postgres_tx, pair):
    """Một quy tắc phiên bản 1 kèm một ngưỡng, chèn trong cùng giao dịch (như API làm)."""
    with postgres_tx.begin() as c:
        rid = c.execute(text(_insert_ddi_sql()), {"a": pair[0], "b": pair[1]}).scalar_one()
        c.execute(
            text(
                f"INSERT INTO {THRESHOLDS} (interaction_id, ingredient_ref, min_dose, dose_unit, "
                "severity_level, warning_text) VALUES (:i, 'A', 100, 'mg/ngày', 3, 'w')"
            ),
            {"i": rid},
        )
    return rid


def _run(engine, sql: str, params: dict):
    """Chạy trong giao dịch riêng rồi rollback; lỗi DB được ném ra."""
    with engine.connect() as c:
        tx = c.begin()
        try:
            return c.execute(text(sql), params)
        finally:
            tx.rollback()


def test_old_style_insert_becomes_open_version_1__AC25(db, rule):
    row = db.execute(
        text(
            "SELECT id, rule_id, version, created_by, superseded_at, deleted_at "
            f"FROM {DDI} WHERE id = :i"
        ),
        {"i": rule},
    ).one()
    assert (row.rule_id, row.version, row.created_by) == (row.id, 1, None)
    assert row.superseded_at is None and row.deleted_at is None


def test_insert_closed_or_versionless_rejected(db, pair):
    with pytest.raises(DBAPIError, match="must be inserted open"):
        db.execute(text(_insert_ddi_sql(", deleted_at", ", now()")), {"a": pair[0], "b": pair[1]})
    with pytest.raises(DBAPIError, match="needs an existing rule_id"):
        db.execute(text(_insert_ddi_sql(", version", ", 2")), {"a": pair[0], "b": pair[1]})


@pytest.mark.parametrize("role", ["api_role", "worker_role", "postgres"])
def test_content_update_rejected_for_every_role__AC22(db, role_engines, rule, role):
    sql = f"UPDATE {DDI} SET severity_level = 4, description = 'x' WHERE id = :i"
    expected = "content is immutable" if role == "postgres" else "permission denied"
    with pytest.raises(DBAPIError, match=expected):
        if role == "postgres":
            db.execute(text(sql), {"i": rule})
        else:
            _run(role_engines[role], sql, {"i": rule})
    assert (
        db.execute(
            text(f"SELECT severity_level FROM {DDI} WHERE id = :i"), {"i": rule}
        ).scalar_one()
        == 2
    )


def test_close_once_then_immutable__AC22(db, role_engines, rule):
    api = role_engines["api_role"]
    with api.begin() as c:
        c.execute(text(f"UPDATE {DDI} SET superseded_at = now() WHERE id = :i"), {"i": rule})
    for sql in (
        f"UPDATE {DDI} SET deleted_at = now() WHERE id = :i",
        f"UPDATE {DDI} SET superseded_at = now() WHERE id = :i",
    ):
        with pytest.raises(DBAPIError, match="closed and immutable"):
            db.execute(text(sql), {"i": rule})


def test_superseded_and_deleted_together_rejected(db, rule):
    with pytest.raises(DBAPIError, match="state_chk"):
        db.execute(
            text(f"UPDATE {DDI} SET superseded_at = now(), deleted_at = now() WHERE id = :i"),
            {"i": rule},
        )


@pytest.mark.parametrize("table", [DDI, THRESHOLDS])
def test_delete_and_truncate_rejected__AC22(db, postgres_tx, role_engines, rule, table):
    column = "interaction_id" if table == THRESHOLDS else "id"
    with pytest.raises(DBAPIError, match="not allowed on the versioned"):
        db.execute(text(f"DELETE FROM {table} WHERE {column} = :i"), {"i": rule})
    with pytest.raises(DBAPIError, match="permission denied"):
        _run(role_engines["api_role"], f"DELETE FROM {table} WHERE {column} = :i", {"i": rule})
    with pytest.raises(DBAPIError, match="not allowed on the versioned"):
        _run(postgres_tx, f"TRUNCATE {table} CASCADE", {})  # rollback dù trigger có hỏng


def test_thresholds_immutable_and_only_added_with_new_version__AC22_AC19(
    db, role_engines, rule, pair
):
    with pytest.raises(DBAPIError, match="not allowed on the versioned"):
        db.execute(
            text(f"UPDATE {THRESHOLDS} SET min_dose = 1 WHERE interaction_id = :i"), {"i": rule}
        )
    with pytest.raises(DBAPIError, match="same transaction"):
        _run(
            role_engines["api_role"],
            f"INSERT INTO {THRESHOLDS} (interaction_id, ingredient_ref, min_dose, dose_unit, "
            "severity_level, warning_text) VALUES (:i, 'A', 1, 'mg', 2, 'x')",
            {"i": rule},
        )
    assert (
        len(
            db.execute(
                text(f"SELECT 1 FROM {THRESHOLDS} WHERE interaction_id = :i"), {"i": rule}
            ).all()
        )
        == 1
    )


def test_worker_role_read_only(role_engines, rule, pair):
    worker = role_engines["worker_role"]
    assert _run(worker, f"SELECT count(*) FROM {DDI} WHERE id = :i", {"i": rule}).scalar_one() == 1
    with pytest.raises(DBAPIError, match="permission denied"):
        _run(worker, _insert_ddi_sql(), {"a": pair[1], "b": pair[0]})
    with pytest.raises(DBAPIError, match="permission denied"):
        _run(worker, f"UPDATE {DDI} SET superseded_at = now() WHERE id = :i", {"i": rule})


@pytest.mark.parametrize("role", ["anon", "authenticated"])
def test_client_roles_cannot_read(postgres_tx, role):
    with postgres_tx.connect() as c, c.begin() as tx:
        c.execute(text(f"SET LOCAL ROLE {role}"))
        assert c.execute(text("SELECT current_user")).scalar_one() == role
        with pytest.raises(DBAPIError, match="permission denied"):
            c.execute(text(f"SELECT 1 FROM {FOOD} LIMIT 1"))
        tx.rollback()


def test_pair_unique_only_among_open_versions__AC24(db, rule, pair):
    with pytest.raises(DBAPIError, match="active_ingredient_interactions_pair_uq"):
        db.execute(text(_insert_ddi_sql()), {"a": pair[1], "b": pair[0]})
    db.execute(text(f"UPDATE {DDI} SET deleted_at = now() WHERE id = :i"), {"i": rule})
    again = db.execute(text(_insert_ddi_sql()), {"a": pair[1], "b": pair[0]}).scalar_one()
    assert again != rule
