"""Gợi ý lại giữ một phần món cũ và giới hạn lượt theo ngày (task 5.11: AC14, AC15, AC27).

Thuần, tất định: không đọc DB hay đồng hồ hệ thống (thời điểm hiện tại được truyền vào).
Món cũ đọc từ `meal_suggestions.suggestion_content` do chính backend ghi, nhưng vẫn được đọc
phòng thủ: món hỏng cấu trúc bị bỏ, không làm hỏng request.
"""

from collections.abc import Iterable, Mapping
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from drugtime.modules.ai_meal.domain.model import (
    BenefitTarget,
    MealBenefit,
    MealDishType,
    MealIngredient,
    MealSuggestion,
)
from drugtime.modules.ai_meal.domain.text_match import contains_any, normalize

VN_TZ = ZoneInfo("Asia/Ho_Chi_Minh")
MAX_TOTAL = 6
MAX_KEPT = 3
NEW_ON_REFRESH = 3
_DISH_TYPES = frozenset(t.value for t in MealDishType)


def day_start_vn(now: datetime) -> datetime:
    """00:00 hôm nay theo giờ Việt Nam, có múi giờ."""
    local = now.astimezone(VN_TZ)
    return local.replace(hour=0, minute=0, second=0, microsecond=0)


def seconds_to_midnight_vn(now: datetime) -> int:
    """Số giây tới 00:00 hôm sau (giờ Việt Nam), tối thiểu 1, dùng cho `Retry-After`."""
    next_midnight = day_start_vn(now) + timedelta(days=1)
    return max(1, int((next_midnight - now.astimezone(VN_TZ)).total_seconds()))


def remaining(limit: int, used: int, *, is_refresh: bool) -> int:
    """Số lần gợi ý lại còn lại sau request hiện tại; không bao giờ âm."""
    return max(0, limit - used - (1 if is_refresh else 0))


def _benefit(raw: Any, allowed: set[tuple[str, str | None]]) -> MealBenefit | None:
    if not isinstance(raw, Mapping):
        return None
    text, related = raw.get("text"), raw.get("related_to")
    if not isinstance(text, str) or not isinstance(related, Mapping):
        return None
    target = (related.get("type"), related.get("label"))
    if target not in allowed:  # bệnh nền / dị ứng / hạn chế không còn trong hồ sơ hiện tại
        return None
    return MealBenefit(text, BenefitTarget(*target))


def _ingredient(raw: Any) -> MealIngredient | None:
    if not isinstance(raw, Mapping):
        return None
    name, amount, group = raw.get("name"), raw.get("amount"), raw.get("group")
    sparingly = raw.get("use_sparingly")
    if not all(isinstance(v, str) for v in (name, amount, group)) or not isinstance(
        sparingly, bool
    ):
        return None
    return MealIngredient(name, amount, group, sparingly)


def _old_dish(
    raw: Any, blocked: tuple[str, ...], allowed: set[tuple[str, str | None]]
) -> MealSuggestion | None:
    if not isinstance(raw, Mapping):
        return None
    name, kcal, minutes = raw.get("name"), raw.get("kcal_estimate"), raw.get("cook_minutes")
    if not isinstance(name, str) or not isinstance(kcal, int) or not isinstance(minutes, int):
        return None
    raw_ingredients = raw.get("ingredients") or []
    ingredients = tuple(i for i in map(_ingredient, raw_ingredients) if i is not None)
    if not ingredients or len(ingredients) != len(raw_ingredients):
        return None
    # QD-41: kiểm lại với dị ứng và thực phẩm cần tránh của request hiện tại (AC15).
    if contains_any(name, blocked) or any(contains_any(i.name, blocked) for i in ingredients):
        return None
    benefits = tuple(
        b for b in (_benefit(x, allowed) for x in raw.get("benefits") or []) if b is not None
    )
    if not benefits:
        return None
    dish_type = raw.get("dish_type")
    image_id = raw.get("image_id")
    tags = tuple(t for t in raw.get("tags") or [] if isinstance(t, str))
    return MealSuggestion(
        name=name,
        tags=tags,
        kcal_estimate=kcal,
        cook_minutes=minutes,
        benefits=benefits,
        ingredients=ingredients,
        # Bản ghi `meal-v1` không có dish_type / image_id.
        dish_type=dish_type if dish_type in _DISH_TYPES else MealDishType.KHAC.value,
        image_query=None,
        is_new=False,
        image_id=image_id if isinstance(image_id, int) and not isinstance(image_id, bool) else None,
    )


def select_kept(
    previous_content: Mapping[str, Any],
    blocked_keywords: Iterable[str],
    targets: Mapping[str, BenefitTarget],
) -> tuple[MealSuggestion, ...]:
    """Tối đa 3 món cũ còn hợp lệ, theo thứ tự gốc; món chính cũ (phần tử đầu) luôn bị bỏ."""
    suggestions = previous_content.get("suggestions")
    if not isinstance(suggestions, list):
        return ()
    blocked = tuple(blocked_keywords)
    allowed = {(t.type, t.label) for t in targets.values()}
    kept: list[MealSuggestion] = []
    for raw in suggestions[1:]:
        dish = _old_dish(raw, blocked, allowed)
        if dish is not None:
            kept.append(dish)
        if len(kept) == MAX_KEPT:
            break
    return tuple(kept)


def old_names(previous_content: Mapping[str, Any]) -> tuple[str, ...]:
    """Tên mọi món của gợi ý trước (kể cả món chính) để LLM tránh lặp."""
    suggestions = previous_content.get("suggestions")
    if not isinstance(suggestions, list):
        return ()
    return tuple(
        s["name"] for s in suggestions if isinstance(s, Mapping) and isinstance(s.get("name"), str)
    )


def merge(
    new: Iterable[MealSuggestion], kept: Iterable[MealSuggestion]
) -> tuple[MealSuggestion, ...]:
    """Món mới trước, món giữ lại sau; khử trùng theo tên chuẩn hóa; tối đa 6 món."""
    result: list[MealSuggestion] = []
    seen: set[str] = set()
    for dish in (*new, *kept):
        key = normalize(dish.name)
        if key in seen:
            continue
        seen.add(key)
        result.append(dish)
        if len(result) == MAX_TOTAL:
            break
    return tuple(result)
