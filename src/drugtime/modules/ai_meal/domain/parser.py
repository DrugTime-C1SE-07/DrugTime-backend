"""Parse và kiểm output của LLM thành `MealSuggestionSet` (task 4.26, AC5–AC7).

Hai pha, tất định:
1. Cấu trúc: sai bất kỳ chỗ nào trong bất kỳ món nào → `LlmInvalidOutput`, không trả một phần.
2. Lọc phòng thủ: bỏ trường lạ, lợi ích có khóa lạ hoặc nhắc thuốc, tag nhắc thuốc, món chứa
   dị ứng / thực phẩm cần tránh, món trùng tên. Còn 0 món → `no_valid_suggestion`.

Task 5.11: `dish_type` bắt buộc (ngoài enum → `khac`); `image_query` không hợp lệ thì bỏ (món vẫn
giữ); khi gợi ý lại, món trùng tên món cũ bị loại và chỉ giữ tối đa `max_new` món.
"""

import json
from dataclasses import dataclass
from typing import Any

from drugtime.modules.ai_meal.domain.errors import LlmInvalidOutput
from drugtime.modules.ai_meal.domain.model import (
    MealBenefit,
    MealDishType,
    MealIngredient,
    MealPrompt,
    MealSuggestion,
    MealSuggestionSet,
)
from drugtime.modules.ai_meal.domain.prompt import IMAGE_QUERY_MAX
from drugtime.modules.ai_meal.domain.text_match import contains_any, normalize

MAX_SUGGESTIONS = 6
GROUPS = frozenset({"chinh", "gia_vi"})
DISH_TYPES = frozenset(t.value for t in MealDishType)


def _fail() -> LlmInvalidOutput:
    return LlmInvalidOutput("schema")


def _obj(value: Any) -> dict:
    if not isinstance(value, dict):
        raise _fail()
    return value


def _text(obj: dict, key: str, max_len: int) -> str:
    value = obj.get(key)
    if not isinstance(value, str):
        raise _fail()
    text = " ".join(value.split())
    if not 1 <= len(text) <= max_len:
        raise _fail()
    return text


def _int(obj: dict, key: str, low: int, high: int) -> int:
    value = obj.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise _fail()
    return value


def _list(obj: dict, key: str, low: int, high: int) -> list:
    value = obj.get(key)
    if not isinstance(value, list) or not low <= len(value) <= high:
        raise _fail()
    return value


@dataclass(frozen=True)
class _Checked:
    """Món đã qua kiểm cấu trúc; lợi ích còn giữ khóa `related_to` thô."""

    meal: MealSuggestion  # benefits rỗng
    raw_benefits: tuple[tuple[str, str], ...]


def _structured(raw: dict, prompt: MealPrompt) -> list[_Checked]:
    if raw.get("meal_type") != prompt.meal_type.value:
        raise _fail()
    meals = []
    for item in _list(raw, "suggestions", 1, MAX_SUGGESTIONS):
        meal = _obj(item)
        benefits = []
        for b in _list(meal, "benefits", 1, 6):
            b = _obj(b)
            related = b.get("related_to")
            if not isinstance(related, str):
                raise _fail()
            benefits.append((_text(b, "text", 60), related.strip()))
        ingredients = []
        for i in _list(meal, "ingredients", 1, 15):
            i = _obj(i)
            group, sparingly = i.get("group"), i.get("use_sparingly")
            if group not in GROUPS or not isinstance(sparingly, bool):
                raise _fail()
            ingredients.append(
                MealIngredient(_text(i, "name", 40), _text(i, "amount", 30), group, sparingly)
            )
        tags = tuple(_text({"t": t}, "t", 20) for t in _list(meal, "tags", 0, 4))
        dish_type = meal.get("dish_type")
        if not isinstance(dish_type, str):
            raise _fail()
        query = meal.get("image_query")
        suggestion = MealSuggestion(
            name=_text(meal, "name", 80),
            tags=tags,
            kcal_estimate=_int(meal, "kcal_estimate", 50, 2000),
            cook_minutes=_int(meal, "cook_minutes", 1, 240),
            benefits=(),
            ingredients=tuple(ingredients),
            dish_type=dish_type if dish_type in DISH_TYPES else MealDishType.KHAC.value,
            image_query=" ".join(query.split()) if isinstance(query, str) else None,
        )
        meals.append(_Checked(suggestion, tuple(benefits)))
    return meals


def _filtered(checked: _Checked, prompt: MealPrompt) -> MealSuggestion | None:
    meal = checked.meal
    blocked = prompt.blocked_food_keywords
    if contains_any(meal.name, blocked) or any(
        contains_any(i.name, blocked) for i in meal.ingredients
    ):
        return None
    drugs = prompt.drug_keywords
    benefits = tuple(
        MealBenefit(text, prompt.targets[related])
        for text, related in checked.raw_benefits
        if related in prompt.targets and not contains_any(text, drugs)
    )
    if not benefits:
        return None
    tags = tuple(t for t in meal.tags if not contains_any(t, drugs))
    query = meal.image_query
    if not query or len(query) > IMAGE_QUERY_MAX or contains_any(query, drugs):
        query = None  # AC9: bỏ cụm từ, món vẫn hợp lệ, không tìm ảnh
    return MealSuggestion(
        name=meal.name,
        tags=tags,
        kcal_estimate=meal.kcal_estimate,
        cook_minutes=meal.cook_minutes,
        benefits=benefits,
        ingredients=meal.ingredients,
        dish_type=meal.dish_type,
        image_query=query,
    )


def parse_suggestions(
    raw: str,
    prompt: MealPrompt,
    *,
    avoid_dish_names: tuple[str, ...] = (),
    max_new: int = MAX_SUGGESTIONS,
) -> MealSuggestionSet:
    """`avoid_dish_names`/`max_new` chỉ dùng khi gợi ý lại (task 5.11)."""
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        raise LlmInvalidOutput("invalid_json") from None
    meals = _structured(_obj(data), prompt)

    kept: list[MealSuggestion] = []
    seen: set[str] = {normalize(n) for n in avoid_dish_names}
    for checked in meals:
        clean = _filtered(checked, prompt)
        key = normalize(checked.meal.name)
        if clean is None or key in seen:
            continue
        seen.add(key)
        kept.append(clean)
        if len(kept) == max_new:
            break
    if not kept:
        raise LlmInvalidOutput("no_valid_suggestion")
    return MealSuggestionSet(prompt.version, prompt.meal_type, tuple(kept))
