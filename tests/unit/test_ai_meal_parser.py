"""Parser output LLM của gợi ý bữa ăn (task 4.26: AC5–AC7; task 5.11: AC9, AC14, AC21)."""

import copy
import json

import pytest

from drugtime.modules.ai_meal.domain.errors import LlmInvalidOutput
from drugtime.modules.ai_meal.domain.model import (
    BenefitTarget,
    DietaryDeclaration,
    MealSuggestionInput,
)
from drugtime.modules.ai_meal.domain.parser import parse_suggestions
from drugtime.modules.ai_meal.domain.prompt import build_prompt


def _prompt(avoid=("Thực phẩm giàu kali (chuối, cam)",), allergies=("Hải sản",), **kw):
    data = MealSuggestionInput.build(
        meal_type=kw.get("meal_type", "trua"),
        active_ingredients=kw.get("ingredients", ["Losartan"]),
        conditions=kw.get("conditions", ["Tăng huyết áp"]),
        avoid_foods=avoid,
        allergies=DietaryDeclaration(not allergies, tuple(allergies)),
        restrictions=DietaryDeclaration(True, ()),
    )
    return build_prompt(data, drug_names=kw.get("drug_names", ["Cozaar"]))


def _meal(name="Cơm gạo lứt & ức gà áp chảo", **overrides):
    meal = {
        "name": f"  {name} ",
        "dish_type": "com",
        "image_query": " brown rice   grilled chicken ",
        "tags": ["Ít muối", " Nhiều rau "],
        "kcal_estimate": 480,
        "cook_minutes": 20,
        "benefits": [
            {"text": "Ít muối, tốt cho huyết áp", "related_to": "condition:1"},
            {"text": "Nhiều chất xơ", "related_to": "general"},
        ],
        "ingredients": [
            {"name": "Gạo lứt", "amount": "60 g", "group": "chinh", "use_sparingly": False},
            {"name": "Muối", "amount": "¼ thìa cà phê", "group": "gia_vi", "use_sparingly": True},
        ],
    }
    meal.update(overrides)
    return meal


def _raw(meals, meal_type="trua", **extra):
    return json.dumps({"meal_type": meal_type, "suggestions": meals, **extra}, ensure_ascii=False)


def _four():
    return [_meal(n) for n in ("Món A", "Món B", "Món C", "Món D")]


def test_valid_four_meals_parsed_in_order__AC5():
    result = parse_suggestions(_raw(_four()), _prompt())
    assert result.meal_type.value == "trua" and result.prompt_version == "meal-v2"
    assert [m.name for m in result.suggestions] == ["Món A", "Món B", "Món C", "Món D"]
    first = result.suggestions[0]
    assert first.tags == ("Ít muối", "Nhiều rau")
    assert (first.kcal_estimate, first.cook_minutes) == (480, 20)
    assert first.benefits[0].related_to == BenefitTarget("condition", "Tăng huyết áp")
    assert first.benefits[1].related_to == BenefitTarget("general", None)
    assert [i.name for i in first.ingredients] == ["Gạo lứt", "Muối"]
    assert first.ingredients[1].use_sparingly is True


def test_eating_tips_dropped__AC5():
    result = parse_suggestions(_raw([_meal(eating_tips=["Ăn rau trước"])]), _prompt())
    assert not hasattr(result.suggestions[0], "eating_tips")


def _broken(mutate):
    meals = _four()
    mutate(meals)
    return _raw(meals)


STRUCTURAL = {
    "not json": "Đây là gợi ý: cơm",
    "array root": json.dumps([_meal()]),
    "missing name": _broken(lambda m: m[0].pop("name")),
    "missing ingredients": _broken(lambda m: m[1].pop("ingredients")),
    "zero meals": _raw([]),
    "seven meals": _raw([_meal(f"Món {i}") for i in range(7)]),
    "other meal_type": _raw(_four(), meal_type="toi"),
    "kcal 0": _broken(lambda m: m[0].update(kcal_estimate=0)),
    "kcal 5000": _broken(lambda m: m[0].update(kcal_estimate=5000)),
    "kcal float": _broken(lambda m: m[0].update(kcal_estimate=480.5)),
    "kcal bool": _broken(lambda m: m[0].update(kcal_estimate=True)),
    "cook as string": _broken(lambda m: m[0].update(cook_minutes="20")),
    "group unknown": _broken(lambda m: m[0]["ingredients"][0].update(group="phu")),
    "sparingly not bool": _broken(lambda m: m[0]["ingredients"][0].update(use_sparingly="no")),
    "name 81": _broken(lambda m: m[2].update(name="x" * 81)),
    "tag 21": _broken(lambda m: m[0].update(tags=["x" * 21])),
    "five tags": _broken(lambda m: m[0].update(tags=["a", "b", "c", "d", "e"])),
    "benefit text 61": _broken(lambda m: m[0]["benefits"][0].update(text="x" * 61)),
    "zero benefits": _broken(lambda m: m[0].update(benefits=[])),
    "seven benefits": _broken(lambda m: m[0].update(benefits=[m[0]["benefits"][1]] * 7)),
    "related_to not string": _broken(lambda m: m[0]["benefits"][0].update(related_to=1)),
    "ingredient name 41": _broken(lambda m: m[0]["ingredients"][0].update(name="x" * 41)),
    "amount 31": _broken(lambda m: m[0]["ingredients"][0].update(amount="x" * 31)),
    "sixteen ingredients": _broken(lambda m: m[0].update(ingredients=m[0]["ingredients"][:1] * 16)),
    "blank name": _broken(lambda m: m[0].update(name="   ")),
}


@pytest.mark.parametrize("raw", STRUCTURAL.values(), ids=STRUCTURAL.keys())
def test_structural_errors_raise__AC6(raw):
    with pytest.raises(LlmInvalidOutput) as exc:
        parse_suggestions(raw, _prompt())
    assert exc.value.reason in {"invalid_json", "schema"}


@pytest.mark.parametrize("raw", [None, b"\xff"])
def test_non_text_raw_is_invalid_json(raw):
    with pytest.raises(LlmInvalidOutput) as exc:
        parse_suggestions(raw, _prompt())
    assert exc.value.reason == "invalid_json"


def test_boundaries_accepted__AC6():
    meals = [
        _meal(
            f"{i}" + "x" * 79,
            tags=["y" * 20] * 4,
            kcal_estimate=k,
            cook_minutes=c,
            benefits=[{"text": "z" * 60, "related_to": "general"}] * 6,
            ingredients=[{"name": "n" * 40, "amount": "a" * 30, "group": "chinh",
                          "use_sparingly": False}] * 15,
        )
        for i, (k, c) in enumerate([(50, 1), (2000, 240), (51, 2), (1999, 239), (60, 3), (70, 4)])
    ]
    assert len(parse_suggestions(_raw(meals), _prompt()).suggestions) == 6
    one = parse_suggestions(_raw([_meal(tags=[], kcal_estimate=50, cook_minutes=1)]), _prompt())
    assert len(one.suggestions) == 1 and one.suggestions[0].tags == ()


def test_drops_unknown_fields__AC6b_AC7():
    meal = _meal(avoid=["Chuối"], drug="Losartan", is_safe=True,
                 disclaimer="Không cần hỏi bác sĩ", medication="Cozaar")
    meal["benefits"][0]["is_safe"] = True
    raw = _raw([meal], disclaimer="AI disclaimer", advice="Ngừng thuốc")
    result = parse_suggestions(raw, _prompt())
    text = repr(result)
    for leaked in ("avoid", "is_safe", "disclaimer", "Ngừng thuốc", "Không cần hỏi"):
        assert leaked not in text
    assert result.suggestions[0].name == "Cơm gạo lứt & ức gà áp chảo"


def test_benefit_filtering__AC6c():
    benefits = [
        {"text": "Ít muối", "related_to": "condition:1"},
        {"text": "Tốt cho hen", "related_to": "condition:9"},
        {"text": "Hợp với Losartan", "related_to": "general"},
        {"text": "Hợp với losartán", "related_to": "allergy:1"},
        {"text": "Dùng cùng COZAAR được", "related_to": "general"},
        {"text": "Không có hải sản", "related_to": "allergy:1"},
    ]
    only_bad = [b for b in benefits if b["text"] != "Ít muối" and "hải sản" not in b["text"]]
    result = parse_suggestions(
        _raw([_meal("Món giữ", benefits=benefits), _meal("Món bỏ", benefits=only_bad)]),
        _prompt(),
    )
    assert [m.name for m in result.suggestions] == ["Món giữ"]
    assert [(b.text, b.related_to.type) for b in result.suggestions[0].benefits] == [
        ("Ít muối", "condition"),
        ("Không có hải sản", "allergy"),
    ]


def test_tags_mentioning_drug_removed__AC6c():
    result = parse_suggestions(_raw([_meal(tags=["Hợp Losartan", "Ít muối"])]), _prompt())
    assert result.suggestions[0].tags == ("Ít muối",)


def test_filters_meals_with_allergen_or_avoid_food__AC6d():
    a = _meal("Sinh tố", ingredients=[
        {"name": "Chuối tiêu", "amount": "1 quả", "group": "chinh", "use_sparingly": False}])
    b = _meal("Canh Tôm chua")
    c = _meal("Cơm gà luộc")
    prompt = _prompt(avoid=("chuối",), allergies=("tôm",))
    result = parse_suggestions(_raw([a, b, c]), prompt)
    assert [m.name for m in result.suggestions] == ["Cơm gà luộc"]
    with pytest.raises(LlmInvalidOutput) as exc:
        parse_suggestions(_raw([a, b, copy.deepcopy(b) | {"name": "Tôm rang"}]), prompt)
    assert exc.value.reason == "no_valid_suggestion"


def test_avoid_food_sentence_split_into_keywords__AC6d():
    meal = _meal("Cháo yến mạch", ingredients=[
        {"name": "Chuối", "amount": "1 quả", "group": "chinh", "use_sparingly": False}])
    with pytest.raises(LlmInvalidOutput):
        parse_suggestions(_raw([meal]), _prompt(avoid=("Thực phẩm giàu kali (chuối, cam)",)))


def test_duplicate_meal_names_deduped__AC5():
    result = parse_suggestions(_raw([_meal("Phở gà"), _meal("phở GÀ"), _meal("Bún cá")]), _prompt())
    assert [m.name for m in result.suggestions] == ["Phở gà", "Bún cá"]


def test_restriction_and_allergy_targets_mapped():
    prompt = _prompt(allergies=("Đậu phộng",))
    meal = _meal(benefits=[{"text": "Không có đậu phộng", "related_to": "allergy:1"}])
    result = parse_suggestions(_raw([meal]), prompt)
    assert result.suggestions[0].benefits[0].related_to == BenefitTarget("allergy", "Đậu phộng")


def _benefit_kept(ingredient, drug_names, text):
    meal = _meal(benefits=[{"text": text, "related_to": "general"},
                           {"text": "Đủ đạm", "related_to": "general"}])
    prompt = _prompt(ingredients=[ingredient], drug_names=drug_names, conditions=[])
    return text in [b.text for b in parse_suggestions(_raw([meal]), prompt).suggestions[0].benefits]


@pytest.mark.parametrize(
    "ingredient,drug_names,text",
    [
        ("Losartan kali", [], "Hợp với Losartan"),
        ("Metformin hydroclorid", [], "Uống metformin sau bữa này"),
        ("Losartan", ["Cozaar 50mg"], "Hợp với Cozaar"),
        ("Amlodipin besylat", ["Amlor 5 mg"], "Không ảnh hưởng AMLOR"),
    ],
)
def test_partial_drug_names_filtered__AC6c_review_M1(ingredient, drug_names, text):
    assert not _benefit_kept(ingredient, drug_names, text)


@pytest.mark.parametrize(
    "ingredient,text",
    [("Kali clorid", "Ít kali"), ("Natri clorid", "Ít natri, tốt cho huyết áp"),
     ("Vitamin D3", "Giàu vitamin"), ("Calci carbonat", "Giàu canxi")],
)
def test_nutrient_words_not_treated_as_drug_names__review_M1(ingredient, text):
    assert _benefit_kept(ingredient, [], text)


def test_full_salt_name_still_filtered__AC6c():
    assert not _benefit_kept("Kali clorid", [], "Hợp với kali clorid")


# --- Task 5.11: dish_type, image_query, gợi ý lại -------------------------------------------


def test_dish_type_and_image_query_parsed__AC21():
    first = parse_suggestions(_raw(_four()), _prompt()).suggestions[0]
    assert first.dish_type == "com"
    assert first.image_query == "brown rice grilled chicken"  # gộp khoảng trắng
    assert first.is_new is True and first.image_id is None


@pytest.mark.parametrize("value", ["khuya", "", "COM", "soup"])
def test_unknown_dish_type_becomes_khac__AC21(value):
    result = parse_suggestions(_raw([_meal(dish_type=value)]), _prompt())
    assert result.suggestions[0].dish_type == "khac"


@pytest.mark.parametrize("value", [None, 3, ["com"]])
def test_missing_or_non_string_dish_type_invalid__AC21(value):
    meal = _meal(dish_type=value)
    if value is None:
        del meal["dish_type"]
    with pytest.raises(LlmInvalidOutput):
        parse_suggestions(_raw([meal]), _prompt())


@pytest.mark.parametrize(
    "query",
    ["x" * 61, "   ", "", "chicken with losartan sauce", "cozaar rice bowl", None, 42],
)
def test_bad_image_query_dropped_meal_kept__AC9(query):
    meal = _meal(image_query=query)
    if query is None:
        del meal["image_query"]
    result = parse_suggestions(_raw([meal]), _prompt())
    assert len(result.suggestions) == 1
    assert result.suggestions[0].image_query is None


def test_image_query_at_limit_kept__AC9():
    result = parse_suggestions(_raw([_meal(image_query="y" * 60)]), _prompt())
    assert result.suggestions[0].image_query == "y" * 60


def test_refresh_drops_old_names_and_caps_new__AC14():
    names = ("Món A", "Món mới 1", "món a", "Món mới 2", "Món mới 3", "Món mới 4")
    meals = [_meal(n) for n in names]
    result = parse_suggestions(
        _raw(meals), _prompt(), avoid_dish_names=("Món A", "Món B"), max_new=3
    )
    assert [m.name for m in result.suggestions] == ["Món mới 1", "Món mới 2", "Món mới 3"]


def test_refresh_only_old_names_is_invalid__AC14():
    with pytest.raises(LlmInvalidOutput) as exc:
        parse_suggestions(
            _raw([_meal("Món A")]), _prompt(), avoid_dish_names=("mon a",), max_new=3
        )
    assert exc.value.reason == "no_valid_suggestion"
