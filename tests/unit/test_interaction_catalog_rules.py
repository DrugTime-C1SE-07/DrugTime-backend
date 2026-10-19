"""Unit test kiểm dữ liệu quy tắc tương tác (task 2.16, AC4, AC9, AC21, AC27)."""

from dataclasses import replace

import pytest

from drugtime.modules.interaction.domain.catalog_rules import (
    DoseThreshold,
    DrugFoodInteractionContent,
    DrugInteractionContent,
    HandlingType,
    InteractionType,
    merge,
    same_content,
    validate_drug_interaction,
)
from drugtime.shared.errors import DomainError


def _rule(**kw) -> DrugInteractionContent:
    base = dict(
        ingredient_a_id=1,
        ingredient_b_id=2,
        ingredient_b_external_name=None,
        interaction_type=InteractionType.DOSE_DEPENDENT,
        severity_level=2,
        handling_type=HandlingType.MONITOR,
        min_interval_hours=None,
        description="d",
        source="s",
        dose_thresholds=(),
    )
    return DrugInteractionContent(**{**base, **kw})


def _th(ref="A", lo=0.0, hi=100.0, sev=2, **kw) -> DoseThreshold:
    return DoseThreshold(ref, lo, hi, kw.get("unit", "mg/ngày"), sev, kw.get("text", "w"))


def _code(rule) -> str | None:
    try:
        validate_drug_interaction(rule)
    except DomainError as exc:
        return str(exc)
    return None


def test_valid_rule_passes():
    assert _code(_rule(dose_thresholds=(_th(), _th("B", 300.0, None, 4)))) is None


def test_same_ingredient_rejected():
    assert _code(_rule(ingredient_b_id=1)) == "same_ingredient"


def test_external_b_is_not_same_ingredient():
    assert _code(_rule(ingredient_b_id=None, ingredient_b_external_name="Rượu")) is None


@pytest.mark.parametrize("sev, expected", [(1, "x"), (2, "x"), (3, "x"), (4, None)])
def test_contraindication_requires_severity_4(sev, expected):
    rule = _rule(
        interaction_type=InteractionType.CONTRAINDICATED,
        handling_type=HandlingType.AVOID,
        severity_level=sev,
    )
    assert _code(rule) == (None if expected is None else "contraindication_severity_mismatch")


def test_contraindication_with_thresholds_rejected():
    rule = _rule(
        interaction_type=InteractionType.CONTRAINDICATED, severity_level=4, dose_thresholds=(_th(),)
    )
    assert _code(rule) == "threshold_not_allowed"


def test_threshold_ref_b_with_external_rejected():
    rule = _rule(
        ingredient_b_id=None, ingredient_b_external_name="Rượu", dose_thresholds=(_th("B"),)
    )
    assert _code(rule) == "threshold_ref_invalid"


@pytest.mark.parametrize(
    "lo, hi, ok",
    [
        (100.0, 50.0, False),
        (None, None, False),
        (50.0, 50.0, True),
        (50.0, None, True),
        (None, 50.0, True),
        (0.0, 0.0, True),
    ],
)
def test_threshold_range(lo, hi, ok):
    assert _code(_rule(dose_thresholds=(_th(lo=lo, hi=hi),))) == (
        None if ok else "threshold_range_invalid"
    )


@pytest.mark.parametrize(
    "handling, hours, ok",
    [
        (HandlingType.SPACING, 2.0, True),
        (HandlingType.SPACING, None, True),
        (HandlingType.MONITOR, None, True),
        (HandlingType.MONITOR, 2.0, False),
        (HandlingType.REDUCE_DOSE, 1.5, False),
    ],
)
def test_min_interval_only_with_cach_gio(handling, hours, ok):
    rule = _rule(handling_type=handling, min_interval_hours=hours)
    assert _code(rule) == (None if ok else "min_interval_not_allowed")


def test_order_same_ingredient_before_severity():
    rule = _rule(
        ingredient_b_id=1, interaction_type=InteractionType.CONTRAINDICATED, severity_level=1
    )
    assert _code(rule) == "same_ingredient"


def test_patch_change_type_keeps_thresholds_rejected():
    current = _rule(dose_thresholds=(_th(),))
    merged = merge(
        current, {"interaction_type": InteractionType.CONTRAINDICATED, "severity_level": 4}
    )
    assert _code(merged) == "threshold_not_allowed"
    cleared = merge(merged, {"dose_thresholds": []})
    assert _code(cleared) is None


def test_patch_change_handling_keeps_interval_rejected():
    current = _rule(handling_type=HandlingType.SPACING, min_interval_hours=2.0)
    merged = merge(current, {"handling_type": HandlingType.MONITOR})
    assert _code(merged) == "min_interval_not_allowed"
    assert _code(merge(merged, {"min_interval_hours": None})) is None


def test_merge_keeps_unsent_fields_and_rejects_unknown():
    current = _rule(dose_thresholds=(_th(),))
    merged = merge(current, {"severity_level": 3, "description": "new"})
    assert merged.severity_level == 3 and merged.description == "new"
    assert merged.dose_thresholds == current.dose_thresholds
    assert merged.source == current.source
    with pytest.raises(ValueError):
        merge(current, {"bogus": 1})


def test_noop_detection():
    a, b = _th("A", 0.0, 100.0, 2), _th("B", 300.0, None, 4)
    current = _rule(dose_thresholds=(a, b))
    with_ids = _rule(dose_thresholds=(replace(b, id=91), replace(a, id=90)))
    assert same_content(current, with_ids)  # thứ tự và id ngưỡng không tính
    assert not same_content(current, replace(current, severity_level=3))
    assert not same_content(current, replace(current, dose_thresholds=(a,)))
    assert same_content(merge(current, {"severity_level": 2}), current)


def test_food_noop_detection():
    food = DrugFoodInteractionContent(1, "Bưởi", 3, "r", "s")
    assert same_content(food, merge(food, {"severity_level": 3}))
    assert not same_content(food, merge(food, {"food_to_avoid": "bưởi"}))
