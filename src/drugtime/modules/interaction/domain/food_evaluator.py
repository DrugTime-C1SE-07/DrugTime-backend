"""Đánh giá tương tác thuốc–thực phẩm (PB25, task 4.05): hàm thuần, tất định (CD7).

Không đọc DB, không gọi LLM. Trạng thái một thuốc theo G11 của task 4.05:
- có ít nhất một quy tắc hiện hành cho một hoạt chất của thuốc → `co_tuong_tac`;
- có hoạt chất nhưng không hoạt chất nào có quy tắc → `da_kiem_tra_khong_thay`
  (không có nghĩa là an toàn: chỉ là không thấy trong dữ liệu hiện có);
- không có hoạt chất trong bảng nối → `khong_du_du_lieu`.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from drugtime.modules.interaction.domain.catalog_rules import (
    DrugFoodInteractionContent,
    RuleRecord,
)
from drugtime.modules.interaction.domain.evaluator import CheckResult

FOOD_DISCLAIMER = (
    "Thông tin chỉ mang tính tham khảo. Hãy hỏi bác sĩ hoặc dược sĩ trước khi "
    "thay đổi việc dùng thuốc hay ăn uống."
)


@dataclass(frozen=True)
class MedicationSummary:
    """Thông tin hiển thị của thuốc trong danh mục."""

    id: int
    name: str
    active_ingredient: str | None
    strength_text: str | None
    dosage_form: str | None


@dataclass(frozen=True)
class FoodCheckMedication:
    user_medication_id: int
    medication: MedicationSummary
    is_active: bool
    ingredient_ids: tuple[int, ...]


@dataclass(frozen=True)
class IngredientRef:
    id: int
    standard_name: str


@dataclass(frozen=True)
class FoodWarning:
    rule_id: int
    version_id: int
    ingredient: IngredientRef
    food_to_avoid: str
    severity_level: int
    reason: str
    source: str


@dataclass(frozen=True)
class FoodMedicationResult:
    user_medication_id: int
    medication: MedicationSummary
    is_active: bool
    status: CheckResult
    ingredients: tuple[IngredientRef, ...]
    warnings: tuple[FoodWarning, ...]


@dataclass(frozen=True)
class FoodReport:
    status: CheckResult
    medications: tuple[FoodMedicationResult, ...]
    disclaimer: str = FOOD_DISCLAIMER


def _ingredient(ingredient_id: int, names: Mapping[int, str]) -> IngredientRef:
    return IngredientRef(ingredient_id, names.get(ingredient_id, f"Hoạt chất #{ingredient_id}"))


def _evaluate_one(
    med: FoodCheckMedication,
    rules_by_ingredient: Mapping[int, list[RuleRecord[DrugFoodInteractionContent]]],
    names: Mapping[int, str],
) -> FoodMedicationResult:
    ingredient_ids = sorted(set(med.ingredient_ids))
    if not ingredient_ids:
        return _result(med, CheckResult.INSUFFICIENT_DATA, (), ())
    ingredients = sorted(
        (_ingredient(i, names) for i in ingredient_ids), key=lambda r: (r.standard_name, r.id)
    )
    warnings = [
        FoodWarning(
            rule_id=rule.meta.rule_id,
            version_id=rule.meta.version_id,
            ingredient=_ingredient(i, names),
            food_to_avoid=rule.content.food_to_avoid,
            severity_level=rule.content.severity_level,
            reason=rule.content.reason,
            source=rule.content.source,
        )
        for i in ingredient_ids
        for rule in rules_by_ingredient.get(i, ())
    ]
    warnings.sort(key=lambda w: (-w.severity_level, w.food_to_avoid, w.version_id))
    status = CheckResult.FOUND if warnings else CheckResult.NONE_FOUND
    return _result(med, status, tuple(ingredients), tuple(warnings))


def _result(
    med: FoodCheckMedication,
    status: CheckResult,
    ingredients: tuple[IngredientRef, ...],
    warnings: tuple[FoodWarning, ...],
) -> FoodMedicationResult:
    return FoodMedicationResult(
        user_medication_id=med.user_medication_id,
        medication=med.medication,
        is_active=med.is_active,
        status=status,
        ingredients=ingredients,
        warnings=warnings,
    )


def overall_status(statuses: Sequence[CheckResult]) -> CheckResult:
    """Có tương tác thắng; danh sách rỗng hoặc có thuốc thiếu dữ liệu → chưa đủ dữ liệu."""
    if CheckResult.FOUND in statuses:
        return CheckResult.FOUND
    if not statuses or CheckResult.INSUFFICIENT_DATA in statuses:
        return CheckResult.INSUFFICIENT_DATA
    return CheckResult.NONE_FOUND


def evaluate_food(
    medications: Sequence[FoodCheckMedication],
    rules: Sequence[RuleRecord[DrugFoodInteractionContent]],
    ingredient_names: Mapping[int, str],
) -> FoodReport:
    """Kết quả theo đúng thứ tự `medications`. Cùng đầu vào luôn cho cùng kết quả."""
    by_ingredient: dict[int, list[RuleRecord[DrugFoodInteractionContent]]] = {}
    for rule in rules:
        by_ingredient.setdefault(rule.content.ingredient_id, []).append(rule)
    results = tuple(_evaluate_one(m, by_ingredient, ingredient_names) for m in medications)
    return FoodReport(overall_status([r.status for r in results]), results)
