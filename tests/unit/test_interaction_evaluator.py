"""Unit tests cho InteractionEvaluator (CD7, NFR03)."""

from drugtime.modules.interaction.domain.catalog_rules import (
    DoseThreshold,
    DrugInteractionContent,
    HandlingType,
    InteractionType,
)
from drugtime.modules.interaction.domain.evaluator import (
    NFR03_DISCLAIMER,
    CheckResult,
    EvaluatedMedication,
    evaluate,
)


def _rule(
    a: int,
    b: int,
    itype: InteractionType = InteractionType.DOSE_DEPENDENT,
    sev: int = 2,
    handling: HandlingType = HandlingType.MONITOR,
    desc: str = "Tăng nguy cơ chảy máu.",
    thresholds: tuple[DoseThreshold, ...] = (),
) -> DrugInteractionContent:
    return DrugInteractionContent(
        ingredient_a_id=a,
        ingredient_b_id=b,
        ingredient_b_external_name=None,
        interaction_type=itype,
        severity_level=sev,
        handling_type=handling,
        min_interval_hours=2.0,
        description=desc,
        source="Dược thư Quốc gia Việt Nam",
        dose_thresholds=thresholds,
    )


def test_evaluate_none_found():
    med1 = EvaluatedMedication(medication_id=1, name="Thuốc A", ingredient_ids=(101,))
    med2 = EvaluatedMedication(medication_id=2, name="Thuốc B", ingredient_ids=(102,))

    names = {101: "Hoạt chất 1", 102: "Hoạt chất 2"}
    result = evaluate([med1, med2], rules=[], ingredient_names=names)

    assert result.status == CheckResult.NONE_FOUND
    assert len(result.interactions) == 0
    assert len(result.insufficient_data_medications) == 0
    assert result.disclaimer == NFR03_DISCLAIMER


def test_evaluate_insufficient_data():
    med1 = EvaluatedMedication(
        medication_id=1, name="Thuốc Đông Y", ingredient_ids=(), has_interaction_data=False
    )
    med2 = EvaluatedMedication(medication_id=2, name="Thuốc Tây", ingredient_ids=(102,))

    result = evaluate([med1, med2], rules=[])

    assert result.status == CheckResult.INSUFFICIENT_DATA
    assert len(result.insufficient_data_medications) == 1
    assert result.insufficient_data_medications[0].medication_id == 1
    assert result.disclaimer == NFR03_DISCLAIMER


def test_evaluate_commutative_matching():
    # Rule định nghĩa: 101 và 102
    rule = _rule(101, 102, sev=3, desc="Hạ huyết áp tư thế nặng")
    names = {101: "Amlodipin", 102: "Simvastatin"}

    # Thứ tự 1: Med 1 có 101, Med 2 có 102
    med1 = EvaluatedMedication(medication_id=1, name="Amlor 5mg", ingredient_ids=(101,))
    med2 = EvaluatedMedication(medication_id=2, name="Zocor 20mg", ingredient_ids=(102,))
    res1 = evaluate([med1, med2], rules=[rule], ingredient_names=names)

    assert res1.status == CheckResult.FOUND
    assert len(res1.interactions) == 1
    assert res1.interactions[0].severity_level == 3
    assert res1.interactions[0].medication_a_id == 1
    assert res1.interactions[0].medication_b_id == 2

    # Thứ tự 2 (ngược lại): Med 2 trước, Med 1 sau
    res2 = evaluate([med2, med1], rules=[rule], ingredient_names=names)
    assert res2.status == CheckResult.FOUND
    assert len(res2.interactions) == 1
    assert res2.interactions[0].severity_level == 3
    assert res2.interactions[0].medication_a_id == 1
    assert res2.interactions[0].medication_b_id == 2


def test_evaluate_contraindicated_severity_4():
    rule = _rule(
        201,
        202,
        itype=InteractionType.CONTRAINDICATED,
        sev=4,
        handling=HandlingType.AVOID,
        desc="Nguy cơ tiêu cơ vân kịch phát đe dọa tính mạng.",
    )
    names = {201: "Gemfibrozil", 202: "Cerivastatin"}

    med1 = EvaluatedMedication(medication_id=10, name="Lopid", ingredient_ids=(201,))
    med2 = EvaluatedMedication(medication_id=20, name="Lipobay", ingredient_ids=(202,))

    result = evaluate([med1, med2], rules=[rule], ingredient_names=names)

    assert result.status == CheckResult.FOUND
    assert len(result.interactions) == 1
    finding = result.interactions[0]
    assert finding.severity_level == 4
    assert "[CHỐNG CHỈ ĐỊNH]" in finding.warning_message
    assert "Gemfibrozil" in finding.warning_message
    assert "Cerivastatin" in finding.warning_message
    assert result.disclaimer == NFR03_DISCLAIMER


def test_evaluate_dose_threshold_matching():
    threshold = DoseThreshold(
        ingredient_ref="A",
        min_dose=40.0,
        max_dose=None,
        dose_unit="mg",
        severity_level=3,
        warning_text="Simvastatin > 40mg tăng nguy cơ tổn thương cơ khi dùng cùng Amlodipin.",
    )
    rule = _rule(301, 302, sev=2, thresholds=(threshold,))
    names = {301: "Simvastatin", 302: "Amlodipin"}

    # Case 1: Liều thấp (20mg) -> Severity 2 (mặc định của rule)
    med1_low = EvaluatedMedication(
        medication_id=1, name="Simva 20", ingredient_ids=(301,), dose_amount=20.0, dose_unit="mg"
    )
    med2 = EvaluatedMedication(medication_id=2, name="Amlo 5", ingredient_ids=(302,))
    res_low = evaluate([med1_low, med2], rules=[rule], ingredient_names=names)
    assert res_low.interactions[0].severity_level == 2

    # Case 2: Liều cao chuẩn đơn vị (80mg) -> Ngưỡng liều kích hoạt: Severity 3
    med1_high = EvaluatedMedication(
        medication_id=1, name="Simva 80", ingredient_ids=(301,), dose_amount=80.0, dose_unit="mg"
    )
    res_high = evaluate([med1_high, med2], rules=[rule], ingredient_names=names)
    assert res_high.interactions[0].severity_level == 3
    assert res_high.interactions[0].warning_message == threshold.warning_text

    # Case 3: Liều cao nhưng đơn vị không tương thích ("viên" vs "mg") -> Giữ Severity 2 mặc định
    med1_incompatible_unit = EvaluatedMedication(
        medication_id=1, name="Simva 80", ingredient_ids=(301,), dose_amount=80.0, dose_unit="viên"
    )
    res_incompatible = evaluate(
        [med1_incompatible_unit, med2], rules=[rule], ingredient_names=names
    )
    assert res_incompatible.interactions[0].severity_level == 2

    # Case 4: Liều cao nhưng thiếu đơn vị (dose_unit=None) -> Không đoán mò, giữ Severity 2 mặc định
    med1_missing_unit = EvaluatedMedication(
        medication_id=1, name="Simva 80", ingredient_ids=(301,), dose_amount=80.0, dose_unit=None
    )
    res_missing = evaluate([med1_missing_unit, med2], rules=[rule], ingredient_names=names)
    assert res_missing.interactions[0].severity_level == 2


def test_evaluate_deduplication():
    # Nhiều thuốc có cùng hoạt chất
    rule = _rule(101, 102, sev=2)
    names = {101: "Paracetamol", 102: "Warfarin"}

    med1 = EvaluatedMedication(medication_id=1, name="Panadol", ingredient_ids=(101,))
    med2 = EvaluatedMedication(medication_id=2, name="Coumadin", ingredient_ids=(102,))

    result = evaluate([med1, med2], rules=[rule, rule], ingredient_names=names)
    assert len(result.interactions) == 1
