"""Tra cứu thực phẩm cần tránh cho thuốc của người bệnh (PB25, task 4.05).

Thứ tự: PEP (ghi access_logs kể cả chính chủ) → thuốc của người bệnh → danh mục → quy tắc
hiện hành → đánh giá tất định. Không cache, không ghi gì ngoài access_logs.
"""

from typing import Protocol
from uuid import UUID

from drugtime.modules.access import api as access
from drugtime.modules.access.domain.rules import Action, Scope
from drugtime.modules.interaction.domain.catalog_rules import (
    DrugFoodInteractionContent,
    RuleRecord,
)
from drugtime.modules.interaction.domain.food_evaluator import (
    FoodCheckMedication,
    FoodReport,
    MedicationSummary,
    evaluate_food,
)
from drugtime.shared.errors import NotFound
from drugtime.shared.uow import UnitOfWork

NOT_FOUND = "user_medication_not_found"


class MedicationRef(Protocol):
    user_medication_id: int
    medication_id: int
    is_active: bool


class PatientMedicationReader(Protocol):
    def active(self, uow: UnitOfWork, patient_id: UUID) -> list[MedicationRef]: ...

    def one(
        self, uow: UnitOfWork, patient_id: UUID, user_medication_id: int
    ) -> MedicationRef | None: ...


class CatalogMedication(Protocol):
    id: int
    name: str
    active_ingredient: str | None
    strength_text: str | None
    dosage_form: str | None


class CatalogMedicationReader(Protocol):
    def get(self, uow: UnitOfWork, medication_id: int) -> CatalogMedication | None:
        """Kể cả thuốc đã xoá mềm khỏi danh mục (G16)."""
        ...


class IngredientReader(Protocol):
    def names(self, uow: UnitOfWork, ids: list[int]) -> dict[int, str]: ...

    def ids_of_medication(self, uow: UnitOfWork, medication_id: int) -> list[int]: ...


class FoodRuleReader(Protocol):
    def active_rules_for_ingredients(
        self, uow: UnitOfWork, ingredient_ids: list[int]
    ) -> list[RuleRecord[DrugFoodInteractionContent]]: ...


def lookup_food_interactions(
    uow: UnitOfWork,
    *,
    caller_id: UUID,
    caller_is_admin: bool,
    patient_id: UUID,
    user_medication_id: int | None,
    medications: PatientMedicationReader,
    catalog: CatalogMedicationReader,
    ingredients: IngredientReader,
    rules: FoodRuleReader,
) -> FoodReport:
    # Kiểm quyền trước mọi lần đọc; người không có quyền nhận 403, không bao giờ 404.
    access.authorize(
        uow,
        caller_id=caller_id,
        caller_is_admin=caller_is_admin,
        patient_id=patient_id,
        scope=Scope.INTERACTIONS,
        action=Action.READ,
        audit_self=True,
    )
    if user_medication_id is None:
        refs = list(medications.active(uow, patient_id))
    else:
        ref = medications.one(uow, patient_id, user_medication_id)
        if ref is None:
            raise NotFound(NOT_FOUND)
        refs = [ref]

    checks: list[FoodCheckMedication] = []
    all_ingredients: set[int] = set()
    for ref in refs:
        info = catalog.get(uow, ref.medication_id)
        if info is None:
            # FK bảo đảm thuốc danh mục tồn tại; thiếu là lỗi dữ liệu, không đoán.
            raise LookupError(f"catalog medication {ref.medication_id} missing")
        ingredient_ids = tuple(ingredients.ids_of_medication(uow, ref.medication_id))
        all_ingredients.update(ingredient_ids)
        checks.append(
            FoodCheckMedication(
                user_medication_id=ref.user_medication_id,
                medication=MedicationSummary(
                    id=info.id,
                    name=info.name,
                    active_ingredient=info.active_ingredient,
                    strength_text=info.strength_text,
                    dosage_form=info.dosage_form,
                ),
                is_active=ref.is_active,
                ingredient_ids=ingredient_ids,
            )
        )

    ids = sorted(all_ingredients)
    names = ingredients.names(uow, ids) if ids else {}
    found = rules.active_rules_for_ingredients(uow, ids)
    return evaluate_food(checks, found, names)
