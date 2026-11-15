"""Gợi ý bữa ăn cho chính người bệnh (PB37, task 4.26).

Thứ tự (AC4, AC10, AC14–AC17):
PEP (ghi access_logs) → khai báo bắt buộc → tính năng bật → đọc thuốc / bệnh nền / quy tắc
thực phẩm (tất định) → prompt → LLM → parse + lọc → lưu. Lỗi ở bất kỳ bước nào trước LLM thì
provider không được gọi. Lỗi lưu hoặc ghi log lan ra để transaction rollback (fail-closed).
"""

from dataclasses import asdict, dataclass
from datetime import datetime
from uuid import UUID

from drugtime.modules.access import api as access
from drugtime.modules.access.domain.rules import Action, Scope
from drugtime.modules.ai_meal.application.ports import (
    ConditionReader,
    FoodCheck,
    FoodCheckReader,
    MealSuggester,
    MealSuggestionStore,
)
from drugtime.modules.ai_meal.domain.errors import LlmDisabled
from drugtime.modules.ai_meal.domain.model import (
    DietaryDeclaration,
    MealSuggestionInput,
    MealSuggestionSet,
)
from drugtime.modules.ai_meal.domain.parser import parse_suggestions
from drugtime.modules.ai_meal.domain.prompt import build_prompt
from drugtime.shared.uow import UnitOfWork


@dataclass(frozen=True)
class MealRequest:
    meal_type: str
    allergies: DietaryDeclaration | None
    dietary_restrictions: DietaryDeclaration | None
    preferences: tuple[str, ...] = ()


@dataclass(frozen=True)
class MealOutcome:
    suggestion_id: int
    created_at: datetime
    result: MealSuggestionSet
    food: FoodCheck


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
) -> MealOutcome:
    """`suggester` = None khi tính năng tắt hoặc thiếu key (AC10)."""
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
    prompt = build_prompt(data, drug_names=check.medication_names)
    result = parse_suggestions(suggester.suggest(prompt), prompt)

    # Chỉ lưu kết quả đã parse; không lưu dị ứng/hạn chế thô từ body.
    content = {
        "prompt_version": result.prompt_version,
        "meal_type": result.meal_type.value,
        "suggestions": [asdict(s) for s in result.suggestions],
    }
    suggestion_id, created_at = store.insert(uow, patient_id, content)
    return MealOutcome(suggestion_id, created_at, result, check)
