"""Gợi ý bữa ăn cho chính người bệnh (PB37, task 4.26; gợi ý lại và ảnh món: task 5.11).

Thứ tự (4.26 AC4, AC10, AC14–AC17; 5.11 contract):
PEP (ghi access_logs) → khai báo bắt buộc → tính năng bật → [gợi ý lại: gợi ý trước (422) →
khóa + đếm lượt (429)] → đọc thuốc / bệnh nền / quy tắc thực phẩm (tất định) → prompt → LLM →
[lần đầu: tra cache CD10 (5.09)] → parse + lọc → [gợi ý lại: lọc lại món cũ, ghép] → giữ chỗ
ảnh → lưu. Lỗi ở bất kỳ bước nào
trước LLM thì provider không được gọi. Lỗi lưu hoặc ghi log lan ra để transaction rollback.
"""

from collections.abc import Callable
from dataclasses import asdict, dataclass, replace
from datetime import datetime
from uuid import UUID

from drugtime.modules.access import api as access
from drugtime.modules.access.domain.rules import Action, Scope
from drugtime.modules.ai_meal.application.ports import (
    ConditionReader,
    FoodCheck,
    FoodCheckReader,
    ImageState,
    MealCache,
    MealImageStore,
    MealSuggester,
    MealSuggestionStore,
)
from drugtime.modules.ai_meal.domain.cache_key import cache_key
from drugtime.modules.ai_meal.domain.errors import (
    LlmDisabled,
    LlmInvalidOutput,
    PreviousSuggestionNotFound,
    RefreshLimitReached,
)
from drugtime.modules.ai_meal.domain.model import (
    DietaryDeclaration,
    MealSuggestion,
    MealSuggestionInput,
    MealSuggestionSet,
)
from drugtime.modules.ai_meal.domain.parser import parse_suggestions
from drugtime.modules.ai_meal.domain.prompt import MealPrompt, build_prompt
from drugtime.modules.ai_meal.domain.refresh import (
    NEW_ON_REFRESH,
    day_start_vn,
    merge,
    old_names,
    remaining,
    seconds_to_midnight_vn,
    select_kept,
)
from drugtime.modules.ai_meal.domain.text_match import normalize
from drugtime.shared import clock
from drugtime.shared.uow import UnitOfWork

DEFAULT_REFRESH_LIMIT = 2


@dataclass(frozen=True)
class MealRequest:
    meal_type: str
    allergies: DietaryDeclaration | None
    dietary_restrictions: DietaryDeclaration | None
    preferences: tuple[str, ...] = ()
    previous_suggestion_id: int | None = None


@dataclass(frozen=True)
class MealOutcome:
    suggestion_id: int
    created_at: datetime
    result: MealSuggestionSet
    food: FoodCheck
    refreshes_remaining: int = DEFAULT_REFRESH_LIMIT
    # Trạng thái ảnh theo image_id của các món trong `result`.
    images: dict[int, ImageState] | None = None
    # Ảnh cần đẩy job Worker; chỉ đẩy sau khi transaction commit.
    enqueue_image_ids: tuple[int, ...] = ()
    cache_status: str = "off"  # off | bypass | hit | miss | corrupt (CD10, task 5.09)


CACHE_OFF, CACHE_BYPASS, CACHE_HIT, CACHE_MISS, CACHE_CORRUPT = (
    "off", "bypass", "hit", "miss", "corrupt"
)


def _first_suggestions(
    suggester: MealSuggester, cache: MealCache | None, prompt: MealPrompt
) -> tuple[MealSuggestionSet, str]:
    """Cache-aside CD10 cho lần gợi ý đầu (5.09 AC3, AC4, AC7, AC12).

    Output lấy từ cache vẫn parse + lọc lại với prompt hiện tại (thực phẩm cần tránh, dị ứng, tên
    thuốc). Chỉ output LLM đã parse thành công mới được ghi; lỗi LLM lan ra, không ghi cache.
    """
    if cache is None:
        return parse_suggestions(suggester.suggest(prompt), prompt), CACHE_OFF
    key = cache_key(prompt)
    status = CACHE_MISS
    cached = cache.get(key)
    if cached is not None:
        try:
            return parse_suggestions(cached, prompt), CACHE_HIT
        except LlmInvalidOutput:
            status = CACHE_CORRUPT  # entry hỏng: coi như miss, ghi đè bằng output mới
    raw = suggester.suggest(prompt)
    result = parse_suggestions(raw, prompt)
    cache.put(key, raw)
    return result, status


def _stored(dish: MealSuggestion) -> dict:
    """Món lưu trong `meal_suggestions`: không có `image_query` (AC9)."""
    data = asdict(dish)
    data.pop("image_query")
    return data


def _with_images(
    uow: UnitOfWork,
    images: MealImageStore,
    dishes: tuple[MealSuggestion, ...],
) -> tuple[tuple[MealSuggestion, ...], dict[int, ImageState], tuple[int, ...]]:
    enqueue: list[int] = []
    reserved: list[MealSuggestion] = []
    for dish in dishes:
        if dish.is_new and dish.image_query:
            r = images.reserve(uow, normalize(dish.name), dish.image_query)
            if r.enqueue:
                enqueue.append(r.image_id)
            dish = replace(dish, image_id=r.image_id)
        reserved.append(dish)
    ids = sorted({d.image_id for d in reserved if d.image_id is not None})
    states = images.states(uow, ids) if ids else {}
    # Ảnh đã bị xóa khỏi metadata: coi như không có ảnh.
    final = tuple(
        d if d.image_id is None or d.image_id in states else replace(d, image_id=None)
        for d in reserved
    )
    return final, states, tuple(enqueue)


def suggest_meals(
    uow: UnitOfWork,
    *,
    caller_id: UUID,
    caller_is_admin: bool,
    patient_id: UUID,
    request: MealRequest,
    suggester: MealSuggester | None,
    food: FoodCheckReader,
    conditions: ConditionReader,
    store: MealSuggestionStore,
    images: MealImageStore | None = None,
    refresh_limit: int = DEFAULT_REFRESH_LIMIT,
    now: Callable[[], datetime] = clock.now,
    cache: MealCache | None = None,
) -> MealOutcome:
    """`suggester` = None khi tính năng tắt hoặc thiếu key (AC10).

    `images` = None khi tính năng ảnh tắt: mọi món có `image_id = None` (5.11 AC8).
    `cache` = None khi cache CD10 tắt (5.09 AC11). Cache chỉ được chạm sau PEP (5.09 AC9).
    """
    # WRITE: chỉ chính chủ có consent ai_meal; người thân, admin, người chờ xóa → 403.
    access.authorize(
        uow,
        caller_id=caller_id,
        caller_is_admin=caller_is_admin,
        patient_id=patient_id,
        scope=Scope.MEAL,
        action=Action.WRITE,
        audit_self=True,
    )
    # Kiểm khai báo trước khi đọc gì thêm (QD-40); raise MealInputIncomplete.
    allergies = DietaryDeclaration.of(request.allergies, "allergies")
    restrictions = DietaryDeclaration.of(request.dietary_restrictions, "dietary_restrictions")
    if suggester is None:
        raise LlmDisabled()

    current = now()
    since = day_start_vn(current)
    previous: dict | None = None
    if request.previous_suggestion_id is not None:
        previous = store.find_previous(uow, request.previous_suggestion_id, patient_id)
        if previous is None or previous.get("meal_type") != request.meal_type:
            raise PreviousSuggestionNotFound()
        # Khóa theo user tới hết transaction: request đồng thời chờ rồi đếm đúng (AC27).
        used = store.count_refreshes(uow, patient_id, since, lock=True)
        if used >= refresh_limit:
            raise RefreshLimitReached(seconds_to_midnight_vn(current))
    else:
        used = store.count_refreshes(uow, patient_id, since, lock=False)

    check = food.read(uow, patient_id)
    data = MealSuggestionInput.build(
        meal_type=request.meal_type,
        active_ingredients=check.ingredient_names,
        conditions=conditions.names(uow, patient_id),
        avoid_foods=[w.food_to_avoid for w in check.warnings],
        allergies=allergies,
        restrictions=restrictions,
        preferences=request.preferences,
    )
    avoid_names = old_names(previous) if previous is not None else ()
    prompt = build_prompt(
        data,
        drug_names=check.medication_names,
        avoid_dish_names=avoid_names,
        count=NEW_ON_REFRESH if previous is not None else None,
    )
    if previous is None:
        result, cache_status = _first_suggestions(suggester, cache, prompt)
        dishes = result.suggestions
    else:
        # Gợi ý lại không dùng cache (5.09 AC10): prompt chứa món cũ nên gần như không trùng.
        cache_status = CACHE_OFF if cache is None else CACHE_BYPASS
        result = parse_suggestions(
            suggester.suggest(prompt), prompt, avoid_dish_names=avoid_names, max_new=NEW_ON_REFRESH
        )
        # QD-41: món cũ kiểm lại với dị ứng và thực phẩm cần tránh hiện tại (AC15).
        kept = select_kept(previous, prompt.blocked_food_keywords, prompt.targets)
        dishes = merge(result.suggestions, kept)

    states: dict[int, ImageState] = {}
    enqueue: tuple[int, ...] = ()
    if images is None:
        dishes = tuple(replace(d, image_id=None) for d in dishes)
    else:
        dishes, states, enqueue = _with_images(uow, images, dishes)
    result = replace(result, suggestions=dishes)

    # Chỉ lưu kết quả đã parse; không lưu dị ứng/hạn chế thô từ body.
    content = {
        "prompt_version": result.prompt_version,
        "meal_type": result.meal_type.value,
        "suggestions": [_stored(s) for s in result.suggestions],
    }
    suggestion_id, created_at = store.insert(
        uow,
        patient_id,
        content,
        request.previous_suggestion_id,
        served_from_cache=cache_status == CACHE_HIT,
    )
    return MealOutcome(
        suggestion_id,
        created_at,
        result,
        check,
        refreshes_remaining=remaining(refresh_limit, used, is_refresh=previous is not None),
        images=states,
        enqueue_image_ids=enqueue,
        cache_status=cache_status,
    )
