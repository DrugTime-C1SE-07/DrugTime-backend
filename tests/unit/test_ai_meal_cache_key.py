"""Cache key gợi ý bữa ăn (task 5.09 AC1, AC2)."""

import re
from dataclasses import replace
from uuid import uuid4

import pytest

from drugtime.modules.ai_meal.domain.cache_key import cache_key
from drugtime.modules.ai_meal.domain.model import DietaryDeclaration, MealSuggestionInput
from drugtime.modules.ai_meal.domain.prompt import build_prompt

BASE = {
    "meal_type": "trua",
    "active_ingredients": ["Metformin", "Losartan"],
    "conditions": ["Tiểu đường type 2"],
    "avoid_foods": ["Bưởi"],
    "allergies": DietaryDeclaration(False, ("Tôm",)),
    "restrictions": DietaryDeclaration(True, ()),
    "preferences": ["Món nước"],
}


def key_of(drug_names=(), **overrides):
    data = MealSuggestionInput.build(**{**BASE, **overrides})
    return cache_key(build_prompt(data, drug_names=drug_names))


def test_same_key_regardless_of_order_case_whitespace__AC1():
    variant = key_of(
        active_ingredients=["  losartan ", "METFORMIN"],
        conditions=["tiểu  đường TYPE 2"],
        avoid_foods=["bưởi"],
        allergies=DietaryDeclaration(False, (" tôm",)),
        preferences=["món   nước "],
    )
    assert variant == key_of()


def test_diacritics_are_not_merged_in_key__AC2():
    # "Cá" và "Cà" là hai thực phẩm khác nhau: chỉ bỏ qua hoa thường, không bỏ dấu.
    assert key_of(allergies=DietaryDeclaration(False, ("Cá",))) != key_of(
        allergies=DietaryDeclaration(False, ("Cà",))
    )


def test_reordering_lists_gives_same_key__AC1():
    assert key_of(active_ingredients=["Losartan", "Metformin"]) == key_of(
        active_ingredients=["Metformin", "Losartan"]
    )
    assert key_of(conditions=["B", "A"]) == key_of(conditions=["A", "B"])


def test_key_prefix_and_no_identifiers_or_brand_names__AC1():
    patient_id = str(uuid4())
    key = key_of(drug_names=["Glucophage 500mg"])
    assert re.fullmatch(r"meal_cache:[0-9a-f]{64}", key)
    for raw in (patient_id, "Glucophage", "Metformin", "Tôm", "trua"):
        assert raw.lower() not in key.lower()
    # Tên biệt dược chỉ dùng lọc output, không vào prompt nên không đổi key.
    assert key == key_of()


@pytest.mark.parametrize(
    "field,value",
    [
        ("meal_type", "toi"),
        ("active_ingredients", ["Metformin"]),
        ("conditions", ["Tăng huyết áp"]),
        ("avoid_foods", ["Bưởi", "Rượu"]),
        ("allergies", DietaryDeclaration(True, ())),
        ("restrictions", DietaryDeclaration(False, ("Ăn chay",))),
        ("preferences", []),
    ],
)
def test_key_changes_per_field__AC2(field, value):
    assert key_of(**{field: value}) != key_of()


def test_key_changes_with_prompt_version__AC2():
    prompt = build_prompt(MealSuggestionInput.build(**BASE))
    assert cache_key(replace(prompt, version="meal-v999")) != cache_key(prompt)
