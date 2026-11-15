"""Adapter gọi module khác qua api.py (task 4.26). Người gọi đã kiểm quyền qua PEP."""

from uuid import UUID

from drugtime.modules.ai_meal.application.ports import FoodCheck, FoodWarningView
from drugtime.modules.interaction import api as interaction
from drugtime.modules.medication import api as medication
from drugtime.shared.uow import UnitOfWork


class InteractionFoodCheck:
    """Gộp báo cáo theo thuốc của 4.05 thành một danh sách "Nên tránh" phẳng."""

    def read(self, uow: UnitOfWork, patient_id: UUID) -> FoodCheck:
        report = interaction.patient_food_report(uow, patient_id)
        warnings: dict[tuple[int, int], FoodWarningView] = {}
        ingredients: set[str] = set()
        medications: set[str] = set()
        for med in report.medications:
            medications.add(med.medication.name)
            ingredients.update(i.standard_name for i in med.ingredients)
            for w in med.warnings:
                # Hai thuốc cùng hoạt chất trả cùng quy tắc: chỉ giữ một.
                warnings[(w.version_id, w.ingredient.id)] = FoodWarningView(
                    rule_id=w.rule_id,
                    version_id=w.version_id,
                    ingredient_id=w.ingredient.id,
                    ingredient_name=w.ingredient.standard_name,
                    food_to_avoid=w.food_to_avoid,
                    severity_level=w.severity_level,
                    reason=w.reason,
                    source=w.source,
                )
        ordered = sorted(
            warnings.values(),
            key=lambda w: (-w.severity_level, w.food_to_avoid, w.version_id, w.ingredient_id),
        )
        return FoodCheck(
            status=report.status.value,
            warnings=tuple(ordered),
            ingredient_names=tuple(sorted(ingredients)),
            medication_names=tuple(sorted(medications)),
        )


class MedicationConditions:
    def names(self, uow: UnitOfWork, patient_id: UUID) -> list[str]:
        return medication.patient_condition_names(uow, patient_id)
