"""Giao diện công khai của interaction."""

from uuid import UUID

from drugtime.modules.interaction.adapters.inbound.http import router
from drugtime.modules.interaction.adapters.outbound import sql_erasure
from drugtime.modules.interaction.adapters.outbound.other_modules import (
    CatalogIngredients,
    CatalogMedications,
    PatientMedications,
)
from drugtime.modules.interaction.adapters.outbound.sql_interaction_rules import (
    SqlDrugFoodInteractions,
)
from drugtime.modules.interaction.application.lookup_food_interactions import build_food_report
from drugtime.modules.interaction.domain.evaluator import CheckResult
from drugtime.modules.interaction.domain.food_evaluator import FoodReport, FoodWarning
from drugtime.shared.uow import UnitOfWork

__all__ = [
    "CheckResult",
    "FoodReport",
    "FoodWarning",
    "eraser",
    "patient_food_report",
    "router",
]


def patient_food_report(uow: UnitOfWork, patient_id: UUID) -> FoodReport:
    """Thực phẩm cần tránh cho mọi thuốc đang dùng (engine tất định 4.05).

    Không kiểm quyền, không ghi access_logs: người gọi phải gọi PEP trước (task 4.26).
    """
    return build_food_report(
        uow,
        patient_id=patient_id,
        user_medication_id=None,
        medications=PatientMedications(),
        catalog=CatalogMedications(),
        ingredients=CatalogIngredients(),
        rules=SqlDrugFoodInteractions(),
    )


class _Eraser:
    name = "interaction"

    def erase_user(self, uow: UnitOfWork, user_id: UUID) -> None:
        sql_erasure.erase(uow, user_id)


eraser = _Eraser()
