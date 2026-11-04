"""InteractionEvaluator: hàm thuần, tất định (CD7). Không đọc DB, không gọi LLM."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum

from drugtime.modules.interaction.domain.catalog_rules import (
    DrugInteractionContent,
    HandlingType,
    InteractionType,
    RuleRecord,
)

NFR03_DISCLAIMER = (
    "DrugTime là hệ thống hỗ trợ quản lý thuốc và cung cấp thông tin tham khảo. "
    "Ứng dụng không thay thế bác sĩ hoặc dược sĩ trong việc ra quyết định lâm sàng."
)


class CheckResult(StrEnum):
    FOUND = "co_tuong_tac"
    NONE_FOUND = "da_kiem_tra_khong_thay"
    INSUFFICIENT_DATA = "khong_du_du_lieu"


@dataclass(frozen=True)
class EvaluatedMedication:
    """Thông tin thuốc đầu vào cần kiểm tra tương tác."""

    medication_id: int
    name: str
    ingredient_ids: tuple[int, ...] = ()
    has_interaction_data: bool = True
    dose_amount: float | None = None
    dose_unit: str | None = None


@dataclass(frozen=True)
class InsufficientDataMedication:
    """Thuốc chưa đủ dữ liệu hoạt chất để đối soát tương tác."""

    medication_id: int
    medication_name: str
    reason: str


@dataclass(frozen=True)
class InteractionFinding:
    """Chi tiết một cặp tương tác phát hiện được."""

    ingredient_a_id: int
    ingredient_a_name: str
    ingredient_b_id: int | None
    ingredient_b_name: str
    medication_a_id: int | None
    medication_a_name: str | None
    medication_b_id: int | None
    medication_b_name: str | None
    severity_level: int
    interaction_type: InteractionType
    handling_type: HandlingType
    min_interval_hours: float | None
    description: str
    warning_message: str
    source: str


@dataclass(frozen=True)
class EvaluationResult:
    """Kết quả tổng hợp đối soát tương tác thuốc (CD7, NFR03)."""

    status: CheckResult
    interactions: tuple[InteractionFinding, ...]
    insufficient_data_medications: tuple[InsufficientDataMedication, ...]
    disclaimer: str = NFR03_DISCLAIMER


def _build_warning_message(
    severity: int,
    name_a: str,
    name_b: str,
    description: str,
    threshold_text: str | None = None,
) -> str:
    if threshold_text:
        return threshold_text
    if severity == 4:
        return f"[CHỐNG CHỈ ĐỊNH] Phối hợp nguy hiểm giữa {name_a} và {name_b}: {description}"
    if severity == 3:
        return f"[CẢNH BÁO NGUY CƠ] Tương tác nghiêm trọng giữa {name_a} và {name_b}: {description}"
    if severity == 2:
        return f"[THẬN TRỌNG] {description}"
    return f"[THEO DÕI] {description}"


def evaluate(
    medications: Sequence[EvaluatedMedication],
    rules: Sequence[RuleRecord[DrugInteractionContent] | DrugInteractionContent],
    ingredient_names: Mapping[int, str] | None = None,
) -> EvaluationResult:
    """Đánh giá tương tác thuốc giữa các thuốc đầu vào theo các quy tắc tương tác (CD7).
    
    Hàm thuần túy, tất định, không truy cập I/O, không gọi DB, không gọi LLM.
    Trả về đúng 3 trạng thái chuẩn và luôn đính kèm disclaimer NFR03.
    """
    names = ingredient_names or {}
    insufficient: list[InsufficientDataMedication] = []
    findings: list[InteractionFinding] = []
    seen_pairs: set[tuple[int, int, int, int]] = set()

    # 1. Phát hiện thuốc thiếu dữ liệu hoạt chất
    for med in medications:
        if not med.has_interaction_data or len(med.ingredient_ids) == 0:
            insufficient.append(
                InsufficientDataMedication(
                    medication_id=med.medication_id,
                    medication_name=med.name,
                    reason="Thuốc chưa có liên kết hoạt chất trong danh mục dược thư",
                )
            )

    # Chuẩn hóa danh sách content từ rules
    rule_contents: list[DrugInteractionContent] = []
    for r in rules:
        if isinstance(r, RuleRecord):
            rule_contents.append(r.content)
        elif isinstance(r, DrugInteractionContent):
            rule_contents.append(r)

    # 2. Đối chiếu từng cặp thuốc khác nhau
    n = len(medications)
    for i in range(n):
        for j in range(i + 1, n):
            med1 = medications[i]
            med2 = medications[j]

            # Bỏ qua nếu bất kỳ thuốc nào thiếu dữ liệu hoạt chất
            if not med1.has_interaction_data or not med2.has_interaction_data:
                continue
            if not med1.ingredient_ids or not med2.ingredient_ids:
                continue

            for ing1 in med1.ingredient_ids:
                for ing2 in med2.ingredient_ids:
                    for rule in rule_contents:
                        # Đối soát tính giao hoán: cặp (A, B) hoặc (B, A)
                        matched = False
                        med_a, med_b = med1, med2
                        ing_a, ing_b = ing1, ing2

                        if rule.ingredient_a_id == ing1 and rule.ingredient_b_id == ing2:
                            matched = True
                            med_a, med_b = med1, med2
                            ing_a, ing_b = ing1, ing2
                        elif rule.ingredient_a_id == ing2 and rule.ingredient_b_id == ing1:
                            matched = True
                            med_a, med_b = med2, med1
                            ing_a, ing_b = ing2, ing1

                        if not matched:
                            continue

                        # Khóa chống trùng lặp: (min_ing, max_ing, min_med, max_med)
                        pair_key = (
                            min(ing1, ing2),
                            max(ing1, ing2),
                            min(med1.medication_id, med2.medication_id),
                            max(med1.medication_id, med2.medication_id),
                        )
                        if pair_key in seen_pairs:
                            continue
                        seen_pairs.add(pair_key)

                        name_a = names.get(ing_a, f"Hoạt chất #{ing_a}")
                        name_b = (
                            names.get(ing_b, f"Hoạt chất #{ing_b}")
                            if ing_b is not None
                            else (rule.ingredient_b_external_name or "Hoạt chất khác")
                        )

                        # Kiểm tra ngưỡng liều nếu có
                        severity = rule.severity_level
                        threshold_text: str | None = None
                        if rule.dose_thresholds:
                            for t in rule.dose_thresholds:
                                ref_med = med_a if t.ingredient_ref == "A" else med_b
                                # Chỉ áp dụng ngưỡng liều khi có liều lượng và đơn vị tương thích
                                unit_matches = (
                                    ref_med.dose_unit is not None
                                    and bool(t.dose_unit)
                                    and ref_med.dose_unit.strip().lower()
                                    == t.dose_unit.strip().lower()
                                )
                                if ref_med.dose_amount is not None and unit_matches:
                                    lo_ok = t.min_dose is None or ref_med.dose_amount >= t.min_dose
                                    hi_ok = t.max_dose is None or ref_med.dose_amount <= t.max_dose
                                    if lo_ok and hi_ok:
                                        severity = t.severity_level
                                        threshold_text = t.warning_text
                                        break

                        warning = _build_warning_message(
                            severity=severity,
                            name_a=name_a,
                            name_b=name_b,
                            description=rule.description,
                            threshold_text=threshold_text,
                        )

                        findings.append(
                            InteractionFinding(
                                ingredient_a_id=ing_a,
                                ingredient_a_name=name_a,
                                ingredient_b_id=ing_b,
                                ingredient_b_name=name_b,
                                medication_a_id=med_a.medication_id,
                                medication_a_name=med_a.name,
                                medication_b_id=med_b.medication_id,
                                medication_b_name=med_b.name,
                                severity_level=severity,
                                interaction_type=rule.interaction_type,
                                handling_type=rule.handling_type,
                                min_interval_hours=rule.min_interval_hours,
                                description=rule.description,
                                warning_message=warning,
                                source=rule.source,
                            )
                        )

    # Sắp xếp các phát hiện theo mức độ nghiêm trọng giảm dần (Severity 4 -> 1)
    findings.sort(key=lambda f: f.severity_level, reverse=True)

    # 3. Xác định trạng thái tổng thể (CD7)
    if len(findings) > 0:
        status = CheckResult.FOUND
    elif len(insufficient) > 0:
        status = CheckResult.INSUFFICIENT_DATA
    else:
        status = CheckResult.NONE_FOUND

    return EvaluationResult(
        status=status,
        interactions=tuple(findings),
        insufficient_data_medications=tuple(insufficient),
        disclaimer=NFR03_DISCLAIMER,
    )
