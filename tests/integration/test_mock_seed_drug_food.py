"""Seed mock thuốc–thực phẩm cho dev (task 4.05: AC19, G13).

Chỉ có ý nghĩa trên DB vừa `supabase db reset` với supabase/seeds/90_mock_drug_food.sql. DB không
có dòng mock nào (ví dụ chạy với cấu hình seed khác) thì skip, có ghi lý do.
"""

from pathlib import Path

import pytest
from sqlalchemy import text

SEED = Path(__file__).resolve().parents[2] / "supabase" / "seeds" / "90_mock_drug_food.sql"
MIGRATIONS = Path(__file__).resolve().parents[2] / "supabase" / "migrations"


def _mock_meds(db):
    rows = db.execute(
        text(
            """
            SELECT m.id, m.name, m.source::text AS source,
                   count(DISTINCT mai.active_ingredient_id) AS ingredients,
                   count(DISTINCT mai.active_ingredient_id) FILTER (WHERE EXISTS (
                       SELECT 1 FROM drug_food_interactions d
                       WHERE d.active_ingredient_id = mai.active_ingredient_id
                         AND d.superseded_at IS NULL AND d.deleted_at IS NULL
                   )) AS ingredients_with_rules,
                   (SELECT count(*) FROM drug_food_interactions d
                    JOIN medication_active_ingredients x
                      ON x.active_ingredient_id = d.active_ingredient_id
                    WHERE x.medication_id = m.id
                      AND d.superseded_at IS NULL AND d.deleted_at IS NULL) AS rules,
                   (SELECT count(DISTINCT d.severity_level) FROM drug_food_interactions d
                    JOIN medication_active_ingredients x
                      ON x.active_ingredient_id = d.active_ingredient_id
                    WHERE x.medication_id = m.id
                      AND d.superseded_at IS NULL AND d.deleted_at IS NULL) AS severities
            FROM medications m
            LEFT JOIN medication_active_ingredients mai ON mai.medication_id = m.id
            WHERE m.name LIKE '[MOCK]%' AND m.deleted_at IS NULL
            GROUP BY m.id ORDER BY m.id
            """
        )
    )
    return [dict(r._mapping) for r in rows]


def test_seed_has_four_mock_shapes_and_labels__AC19(db):
    meds = _mock_meds(db)
    if not meds:
        pytest.skip("DB chưa nạp seeds/90_mock_drug_food.sql (cần `supabase db reset`)")

    one_ingredient_multi_rules = [
        m for m in meds if m["ingredients"] == 1 and m["rules"] >= 2 and m["severities"] >= 2
    ]
    combo_one_with_rule = [
        m for m in meds if m["ingredients"] == 2 and m["ingredients_with_rules"] == 1
    ]
    with_ingredient_no_rule = [m for m in meds if m["ingredients"] >= 1 and m["rules"] == 0]
    no_ingredient = [m for m in meds if m["ingredients"] == 0]
    assert one_ingredient_multi_rules and combo_one_with_rule
    assert with_ingredient_no_rule and no_ingredient
    # Thuốc mock nằm ngoài nguồn đồng bộ danh mục (catalog sync chỉ xoá theo source).
    assert all(m["source"] is None for m in meds)

    mock_ingredient_ids = [
        r.id
        for r in db.execute(
            text(
                "SELECT DISTINCT mai.active_ingredient_id AS id FROM medication_active_ingredients"
                " mai JOIN medications m ON m.id = mai.medication_id WHERE m.name LIKE '[MOCK]%'"
            )
        )
    ]
    labels = db.execute(
        text(
            "SELECT bool_and(a.source LIKE 'MOCK%') FROM active_ingredients a "
            "WHERE a.id = ANY(:ids)"
        ),
        {"ids": mock_ingredient_ids},
    ).scalar_one()
    assert labels is True
    rules = db.execute(
        text(
            "SELECT source, reason, verification_status, rule_id FROM drug_food_interactions "
            "WHERE active_ingredient_id = ANY(:ids)"
        ),
        {"ids": mock_ingredient_ids},
    ).all()
    assert rules
    assert all(r.source.startswith("MOCK") and r.reason.startswith("[MOCK]") for r in rules)
    assert all(r.verification_status == "da_xac_minh" and r.rule_id is not None for r in rules)


def test_mock_data_only_in_seed_file_not_migrations__AC20():
    assert SEED.exists()
    for migration in MIGRATIONS.glob("*.sql"):
        assert "[MOCK]" not in migration.read_text(encoding="utf-8"), migration.name
