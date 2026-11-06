"""Unit test evaluate_food (task 4.05: AC2–AC6, AC15, AC16; G5, G11)."""

import ast
from datetime import UTC, datetime
from pathlib import Path

import pytest

from drugtime.modules.interaction.domain import food_evaluator
from drugtime.modules.interaction.domain.catalog_rules import (
    DrugFoodInteractionContent,
    RuleRecord,
    VersionMeta,
)
from drugtime.modules.interaction.domain.evaluator import CheckResult
from drugtime.modules.interaction.domain.food_evaluator import (
    FOOD_DISCLAIMER,
    FoodCheckMedication,
    MedicationSummary,
    evaluate_food,
    overall_status,
)

T0 = datetime(2026, 11, 6, tzinfo=UTC)
X, Y, Z = 11, 12, 13
NAMES = {X: "Metronidazol", Y: "Ibuprofen", Z: "Paracetamol"}


def rule(version_id: int, ingredient: int, food: str, severity: int) -> RuleRecord:
    return RuleRecord(
        content=DrugFoodInteractionContent(
            ingredient_id=ingredient,
            food_to_avoid=food,
            severity_level=severity,
            reason=f"reason {version_id}",
            source=f"source {version_id}",
        ),
        meta=VersionMeta(
            rule_id=version_id + 1000,
            version=1,
            version_id=version_id,
            rule_created_at=T0,
            created_at=T0,
            created_by=None,
            superseded_at=None,
            deleted_at=None,
            deleted_by=None,
        ),
    )


def med(um_id: int, *ingredients: int, active: bool = True) -> FoodCheckMedication:
    return FoodCheckMedication(
        user_medication_id=um_id,
        medication=MedicationSummary(um_id + 500, f"Thuốc {um_id}", None, None, None),
        is_active=active,
        ingredient_ids=tuple(ingredients),
    )


def test_single_ingredient_with_rule_is_found__AC1():
    report = evaluate_food([med(1, X)], [rule(7, X, "Rượu", 3)], NAMES)
    [m] = report.medications
    assert m.status is CheckResult.FOUND
    [w] = m.warnings
    assert (w.rule_id, w.version_id, w.food_to_avoid, w.severity_level) == (1007, 7, "Rượu", 3)
    assert (w.ingredient.id, w.ingredient.standard_name) == (X, "Metronidazol")
    assert (w.reason, w.source) == ("reason 7", "source 7")
    assert report.disclaimer == FOOD_DISCLAIMER


def test_all_rules_of_all_ingredients_listed_and_sorted__AC2():
    rules = [
        rule(1, X, "Sữa", 2),
        rule(2, X, "Rượu", 4),
        rule(3, Y, "Bưởi", 2),
        rule(4, Y, "Rượu", 4),
    ]
    [m] = evaluate_food([med(1, X, Y)], rules, NAMES).medications
    assert [(w.severity_level, w.food_to_avoid, w.version_id) for w in m.warnings] == [
        (4, "Rượu", 2),
        (4, "Rượu", 4),
        (2, "Bưởi", 3),
        (2, "Sữa", 1),
    ]


def test_same_food_from_two_ingredients_not_merged__G5():
    [m] = evaluate_food(
        [med(1, X, Y)], [rule(1, X, "Rượu", 3), rule(2, Y, "Rượu", 3)], NAMES
    ).medications
    assert [w.ingredient.id for w in m.warnings] == [X, Y]


def test_combo_one_ingredient_with_rule_only_its_warnings__AC5():
    [m] = evaluate_food([med(1, X, Z)], [rule(1, X, "Rượu", 3)], NAMES).medications
    assert m.status is CheckResult.FOUND
    assert {w.ingredient.id for w in m.warnings} == {X}
    assert [i.standard_name for i in m.ingredients] == ["Metronidazol", "Paracetamol"]


def test_ingredients_without_rules_is_none_found__AC3():
    [m] = evaluate_food([med(1, Z)], [rule(1, X, "Rượu", 3)], NAMES).medications
    assert m.status is CheckResult.NONE_FOUND
    assert m.warnings == ()
    assert [i.id for i in m.ingredients] == [Z]


def test_no_ingredients_is_insufficient_even_with_rules_present__AC4():
    [m] = evaluate_food([med(1)], [rule(1, X, "Rượu", 3)], NAMES).medications
    assert m.status is CheckResult.INSUFFICIENT_DATA
    assert (m.ingredients, m.warnings) == ((), ())


@pytest.mark.parametrize(
    "statuses,expected",
    [
        ([CheckResult.FOUND, CheckResult.INSUFFICIENT_DATA], CheckResult.FOUND),
        ([CheckResult.NONE_FOUND, CheckResult.FOUND], CheckResult.FOUND),
        ([CheckResult.NONE_FOUND, CheckResult.INSUFFICIENT_DATA], CheckResult.INSUFFICIENT_DATA),
        ([CheckResult.NONE_FOUND, CheckResult.NONE_FOUND], CheckResult.NONE_FOUND),
        ([], CheckResult.INSUFFICIENT_DATA),
    ],
)
def test_overall_status_precedence__AC6(statuses, expected):
    assert overall_status(statuses) is expected


def test_report_overall_from_medications__AC6():
    meds = [med(1, X), med(2, Z), med(3)]
    report = evaluate_food(meds, [rule(1, X, "Rượu", 3)], NAMES)
    assert [m.status for m in report.medications] == [
        CheckResult.FOUND,
        CheckResult.NONE_FOUND,
        CheckResult.INSUFFICIENT_DATA,
    ]
    assert report.status is CheckResult.FOUND
    assert [m.user_medication_id for m in report.medications] == [1, 2, 3]


def test_empty_medication_list_is_insufficient_with_disclaimer__AC15_AC16():
    report = evaluate_food([], [], {})
    assert report.status is CheckResult.INSUFFICIENT_DATA
    assert report.medications == ()
    assert report.disclaimer.strip()
    assert "bác sĩ" in report.disclaimer and "dược sĩ" in report.disclaimer


def test_inactive_flag_passed_through__AC8():
    [m] = evaluate_food([med(1, X, active=False)], [], NAMES).medications
    assert m.is_active is False


def test_missing_ingredient_name_falls_back():
    [m] = evaluate_food([med(1, 99)], [], {}).medications
    assert m.ingredients[0].standard_name == "Hoạt chất #99"


def test_deterministic_same_input_same_output__AC6():
    rules = [rule(1, X, "Sữa", 2), rule(2, X, "Rượu", 4), rule(3, Y, "Rượu", 4)]
    meds = [med(1, Y, X), med(2, Z)]
    first = evaluate_food(meds, rules, NAMES)
    assert evaluate_food(meds, list(reversed(rules)), NAMES) == first
    assert evaluate_food(meds, rules, NAMES) == first


def test_module_has_no_io_imports__AC6():
    tree = ast.parse(Path(food_evaluator.__file__).read_text(encoding="utf-8"))
    imported = {
        n.module if isinstance(n, ast.ImportFrom) else a.name
        for n in ast.walk(tree)
        if isinstance(n, ast.Import | ast.ImportFrom)
        for a in (n.names if isinstance(n, ast.Import) else [None])
    }
    forbidden = ("sqlalchemy", "httpx", "requests", "openai", "anthropic", "drugtime.shared.db")
    assert not [m for m in imported if m and m.startswith(forbidden)]
