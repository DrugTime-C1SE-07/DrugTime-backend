"""Kiểm tra tương tác thuốc của người bệnh (PB24, Task 4.02).

Tuân thủ CD7 (tất định, không gọi LLM), NFR03 (disclaimer bắt buộc), DK3 (phân quyền).
"""

from uuid import UUID

from sqlalchemy import text

from drugtime.modules.access import api as access
from drugtime.modules.access.domain.rules import Action, Scope
from drugtime.modules.catalog import api as catalog
from drugtime.modules.interaction.adapters.outbound.sql_interaction_rules import (
    SqlDrugInteractions,
)
from drugtime.modules.interaction.domain.evaluator import (
    EvaluatedMedication,
    EvaluationResult,
    evaluate,
)
from drugtime.shared.errors import DomainError
from drugtime.shared.uow import UnitOfWork


def check_patient_interactions(
    uow: UnitOfWork,
    *,
    caller_id: UUID,
    caller_is_admin: bool,
    patient_id: UUID,
    candidate_medication_id: int | None = None,
    candidate_dose_amount: float | None = None,
    candidate_dose_unit: str | None = None,
    medication_ids: list[int] | None = None,
) -> EvaluationResult:
    """Kiểm tra tương tác thuốc giữa ứng viên mới và thuốc đang dùng của bệnh nhân."""
    # 1. Phân quyền DK3: Scope.INTERACTIONS, Action.READ
    access.authorize(
        uow,
        caller_id=caller_id,
        caller_is_admin=caller_is_admin,
        patient_id=patient_id,
        scope=Scope.INTERACTIONS,
        action=Action.READ,
    )

    # 2. Thu thập danh sách thuốc đang dùng của bệnh nhân từ server DB và chuẩn bị liều lượng
    rows = uow.connection.execute(
        text(
            "SELECT medication_id, quantity_per_dose FROM user_medications "
            "WHERE user_id = :p AND deleted_at IS NULL AND ended_at IS NULL"
        ),
        {"p": patient_id},
    ).all()

    patient_active_doses: dict[int, float | None] = {}
    for r in rows:
        if r.quantity_per_dose is not None:
            try:
                patient_active_doses[r.medication_id] = float(r.quantity_per_dose)
            except (ValueError, TypeError):
                patient_active_doses[r.medication_id] = None
        else:
            patient_active_doses[r.medication_id] = None

    catalog_med_ids: list[int] = []
    med_doses: dict[int, float | None] = {}

    if medication_ids is not None:
        # Nếu client truyền danh sách cụ thể
        catalog_med_ids.extend(medication_ids)
    else:
        # Nếu không truyền, lấy danh sách thuốc đang dùng (chưa kết thúc, chưa xoá) của bệnh nhân
        catalog_med_ids.extend(patient_active_doses.keys())

    # Đồng bộ liều lượng từ DB cho các thuốc đang dùng của bệnh nhân
    # (không làm mất quantity_per_dose khi client gửi medication_ids)
    for med_id in catalog_med_ids:
        if med_id in patient_active_doses:
            med_doses[med_id] = patient_active_doses[med_id]

    if candidate_medication_id is not None:
        if candidate_medication_id not in catalog_med_ids:
            catalog_med_ids.append(candidate_medication_id)
        if candidate_dose_amount is not None:
            med_doses[candidate_medication_id] = candidate_dose_amount

    # Loại bỏ trùng lặp giữ nguyên thứ tự
    unique_ids = list(dict.fromkeys(catalog_med_ids))

    if not unique_ids:
        # Người bệnh không có thuốc nào và không truyền thuốc ứng viên
        return evaluate([], rules=[], ingredient_names={})

    # 3. Lấy thông tin chi tiết từng thuốc từ danh mục catalog
    evaluated_meds: list[EvaluatedMedication] = []
    all_ingredient_ids: set[int] = set()

    for med_id in unique_ids:
        cat_med = catalog.get_medication(uow, med_id, include_deleted=True)
        if cat_med is None:
            # Thuốc không tồn tại trong danh mục -> 422
            raise DomainError("catalog_medication_not_found")

        ing_ids = catalog.ingredient_ids_of_medication(uow, med_id)
        all_ingredient_ids.update(ing_ids)

        has_data = cat_med.has_active_ingredients and len(ing_ids) > 0

        dose_amt = (
            candidate_dose_amount
            if med_id == candidate_medication_id and candidate_dose_amount is not None
            else med_doses.get(med_id)
        )
        dose_u = candidate_dose_unit if med_id == candidate_medication_id else None

        evaluated_meds.append(
            EvaluatedMedication(
                medication_id=med_id,
                name=cat_med.name,
                ingredient_ids=tuple(ing_ids),
                has_interaction_data=has_data,
                dose_amount=dose_amt,
                dose_unit=dose_u,
            )
        )

    # 4. Lấy quy tắc tương tác đang có hiệu lực từ DB
    rules = []
    ingredient_names = {}
    if all_ingredient_ids:
        ingredient_names = catalog.ingredient_names(uow, list(all_ingredient_ids))
        rules = SqlDrugInteractions().active_rules_for_ingredients(uow, list(all_ingredient_ids))

    # 5. Gọi hàm domain evaluator tất định (CD7)
    return evaluate(evaluated_meds, rules, ingredient_names=ingredient_names)
