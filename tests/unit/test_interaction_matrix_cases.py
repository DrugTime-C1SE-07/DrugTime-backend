"""Automated tests cho Ma trận kiểm thử Task 4.03 (sprint4_plan/PB24/4.03_test_matrix.md).

Bao gồm:
1. Unit tests synthetic bằng fixture nhân tạo tất định:
   - Polypharmacy (TC-POLY-01, TC-POLY-02)
   - Tính giao hoán A+B = B+A (TC-COMM-01, TC-COMM-02)
   - Thiếu hoạt chất & Phản hồi hỗn hợp (TC-INSUF-01, TC-INSUF-02)
   - DoseThreshold đơn vị liều (TC-DOSE-01, TC-DOSE-02, TC-DOSE-03, TC-DOSE-04)
   - Khử trùng lặp (TC-DEDUP-01)
   - Pháp lý Disclaimer NFR03 (TC-DISC-01)
2. Draft-conformance tests cho các ca lâm sàng provisional:
   - 10 ca dương tính Đái tháo đường (TC-POS-01 .. TC-POS-10)
   - 5 ca candidate âm tính theo phác đồ điều trị (TC-NEG-01 .. TC-NEG-05)

LƯU Ý KIỂM TOÁN:
- Toàn bộ ca synthetic sử dụng fixture nhân tạo độc lập, không đại diện tương tác thật.
- Các ca lâm sàng chỉ xác nhận conformance kỹ thuật với rule dự thảo Task 4.01,
  tuyệt đối KHÔNG tính vào True Positive / False Positive lâm sàng vì chưa có sign-off.
"""

import pytest

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


def _synthetic_rule(
    a_id: int,
    b_id: int,
    itype: InteractionType = InteractionType.DOSE_DEPENDENT,
    sev: int = 2,
    handling: HandlingType = HandlingType.MONITOR,
    desc: str = "Synthetic interaction description",
    thresholds: tuple[DoseThreshold, ...] = (),
) -> DrugInteractionContent:
    return DrugInteractionContent(
        ingredient_a_id=a_id,
        ingredient_b_id=b_id,
        ingredient_b_external_name=None,
        interaction_type=itype,
        severity_level=sev,
        handling_type=handling,
        min_interval_hours=2.0,
        description=desc,
        source="Synthetic Fixture Specification",
        dose_thresholds=thresholds,
    )


# ==============================================================================
# PHÂN NHÓM 3: ĐA THUỐC KỸ THUẬT (POLYPHARMACY >= 3 THUỐC SYNTHETIC)
# ==============================================================================


def test_tc_poly_01_three_medications_one_interaction():
    """[TC-POLY-01] Đơn 3 thuốc synthetic: 1 cặp tương tác nhân tạo + 1 thuốc không tương tác."""
    med_b = EvaluatedMedication(medication_id=2, name="Fixture Drug B", ingredient_ids=(1002,))
    med_a = EvaluatedMedication(medication_id=1, name="Fixture Drug A", ingredient_ids=(1001,))
    med_c = EvaluatedMedication(medication_id=3, name="Fixture Drug C", ingredient_ids=(1003,))

    rule_ab = _synthetic_rule(
        1001, 1002, itype=InteractionType.CONTRAINDICATED, sev=4, handling=HandlingType.AVOID
    )
    names = {1001: "FIX-ING-A", 1002: "FIX-ING-B", 1003: "FIX-ING-C"}

    res = evaluate([med_b, med_a, med_c], rules=[rule_ab], ingredient_names=names)

    assert res.status == CheckResult.FOUND
    assert len(res.interactions) == 1
    finding = res.interactions[0]
    assert finding.severity_level == 4
    assert finding.medication_a_id == 1
    assert finding.medication_b_id == 2
    assert res.disclaimer == NFR03_DISCLAIMER


def test_tc_poly_02_four_medications_two_independent_interactions():
    """[TC-POLY-02] Đơn 4 thuốc synthetic: 2 cặp tương tác nhân tạo độc lập."""
    med_a = EvaluatedMedication(medication_id=1, name="Fixture Drug A", ingredient_ids=(1001,))
    med_b = EvaluatedMedication(medication_id=2, name="Fixture Drug B", ingredient_ids=(1002,))
    med_c = EvaluatedMedication(medication_id=3, name="Fixture Drug C", ingredient_ids=(1003,))
    med_d = EvaluatedMedication(medication_id=4, name="Fixture Drug D", ingredient_ids=(1004,))

    rule_ab = _synthetic_rule(1001, 1002, sev=3, desc="Synthetic A+B")
    rule_cd = _synthetic_rule(1003, 1004, sev=2, desc="Synthetic C+D")
    names = {1001: "FIX-ING-A", 1002: "FIX-ING-B", 1003: "FIX-ING-C", 1004: "FIX-ING-D"}

    res = evaluate([med_a, med_b, med_c, med_d], rules=[rule_ab, rule_cd], ingredient_names=names)

    assert res.status == CheckResult.FOUND
    assert len(res.interactions) == 2
    severities = {f.severity_level for f in res.interactions}
    assert severities == {3, 2}
    med_pairs = {(f.medication_a_id, f.medication_b_id) for f in res.interactions}
    assert med_pairs == {(1, 2), (3, 4)}
    assert res.disclaimer == NFR03_DISCLAIMER


# ==============================================================================
# PHÂN NHÓM 4: TÍNH GIAO HOÁN KỸ THUẬT (A+B = B+A)
# ==============================================================================


def test_tc_comm_01_and_02_commutativity():
    """[TC-COMM-01 & TC-COMM-02] Kiểm tra tính giao hoán độc lập thứ tự."""
    med_a = EvaluatedMedication(medication_id=1, name="Fixture Drug A", ingredient_ids=(1001,))
    med_b = EvaluatedMedication(medication_id=2, name="Fixture Drug B", ingredient_ids=(1002,))

    rule = _synthetic_rule(1001, 1002, sev=4, desc="Commutative test rule")
    names = {1001: "FIX-ING-A", 1002: "FIX-ING-B"}

    # TC-COMM-01: A trước, B sau
    res_ab = evaluate([med_a, med_b], rules=[rule], ingredient_names=names)
    # TC-COMM-02: B trước, A sau
    res_ba = evaluate([med_b, med_a], rules=[rule], ingredient_names=names)

    assert res_ab.status == CheckResult.FOUND
    assert res_ba.status == CheckResult.FOUND
    assert len(res_ab.interactions) == 1
    assert len(res_ba.interactions) == 1

    f_ab = res_ab.interactions[0]
    f_ba = res_ba.interactions[0]

    assert f_ab.medication_a_id == 1 and f_ab.medication_b_id == 2
    assert f_ba.medication_a_id == 1 and f_ba.medication_b_id == 2
    assert f_ab.severity_level == f_ba.severity_level == 4
    assert f_ab.warning_message == f_ba.warning_message
    assert res_ab.disclaimer == res_ba.disclaimer == NFR03_DISCLAIMER


# ==============================================================================
# PHÂN NHÓM 5: THIẾU HOẠT CHẤT & PHẢN HỒI HỖN HỢP KỸ THUẬT
# ==============================================================================


def test_tc_insuf_01_candidate_missing_active_ingredients():
    """[TC-INSUF-01] Thuốc ứng viên synthetic thiếu hoạt chất -> khong_du_du_lieu."""
    med_unk = EvaluatedMedication(
        medication_id=99,
        name="Fixture Drug Unknown",
        ingredient_ids=(),
        has_interaction_data=False,
    )
    med_a = EvaluatedMedication(medication_id=1, name="Fixture Drug A", ingredient_ids=(1001,))

    res = evaluate([med_unk, med_a], rules=[])

    assert res.status == CheckResult.INSUFFICIENT_DATA
    assert len(res.interactions) == 0
    assert len(res.insufficient_data_medications) == 1
    assert res.insufficient_data_medications[0].medication_id == 99
    assert res.disclaimer == NFR03_DISCLAIMER


def test_tc_insuf_02_mixed_response_evaluator():
    """[TC-INSUF-02] Phản hồi hỗn hợp synthetic: vừa có tương tác vừa có thuốc thiếu hoạt chất."""
    med_b = EvaluatedMedication(medication_id=2, name="Fixture Drug B", ingredient_ids=(1002,))
    med_a = EvaluatedMedication(medication_id=1, name="Fixture Drug A", ingredient_ids=(1001,))
    med_unk = EvaluatedMedication(
        medication_id=98,
        name="Fixture Drug Unknown",
        ingredient_ids=(),
        has_interaction_data=False,
    )

    rule = _synthetic_rule(1001, 1002, sev=4)
    names = {1001: "FIX-ING-A", 1002: "FIX-ING-B"}

    res = evaluate([med_b, med_a, med_unk], rules=[rule], ingredient_names=names)

    # Khi có cả tương tác lẫn thuốc thiếu hoạt chất: status là FOUND (co_tuong_tac)
    # và trả về cả 2 danh sách song song
    assert res.status == CheckResult.FOUND
    assert len(res.interactions) == 1
    assert res.interactions[0].severity_level == 4
    assert len(res.insufficient_data_medications) == 1
    assert res.insufficient_data_medications[0].medication_id == 98
    assert res.disclaimer == NFR03_DISCLAIMER


# ==============================================================================
# PHÂN NHÓM 6: NGƯỠNG LIỀU & AN TOÀN ĐƠN VỊ LIỀU KỸ THUẬT
# ==============================================================================


@pytest.fixture
def dose_threshold_rule():
    threshold = DoseThreshold(
        ingredient_ref="A",
        min_dose=40.0,
        max_dose=None,
        dose_unit="mg",
        severity_level=3,
        warning_text="Liều synthetic Alpha > 40mg tăng nguy cơ khi phối hợp Beta.",
    )
    return _synthetic_rule(1301, 1302, sev=2, thresholds=(threshold,))


def test_tc_dose_01_incompatible_unit_fallback(dose_threshold_rule):
    """[TC-DOSE-01] Đơn vị liều không khớp ('viên' vs 'mg') -> Fallback Severity 2."""
    med_alpha = EvaluatedMedication(
        medication_id=301,
        name="Fixture Drug Alpha",
        ingredient_ids=(1301,),
        dose_amount=80.0,
        dose_unit="viên",
    )
    med_beta = EvaluatedMedication(
        medication_id=302, name="Fixture Drug Beta", ingredient_ids=(1302,)
    )
    names = {1301: "FIX-ING-ALPHA", 1302: "FIX-ING-BETA"}

    res = evaluate([med_alpha, med_beta], rules=[dose_threshold_rule], ingredient_names=names)
    assert res.interactions[0].severity_level == 2


def test_tc_dose_02_missing_unit_fallback(dose_threshold_rule):
    """[TC-DOSE-02] Đơn vị liều bị thiếu (None) -> Fallback Severity 2."""
    med_alpha = EvaluatedMedication(
        medication_id=301,
        name="Fixture Drug Alpha",
        ingredient_ids=(1301,),
        dose_amount=80.0,
        dose_unit=None,
    )
    med_beta = EvaluatedMedication(
        medication_id=302, name="Fixture Drug Beta", ingredient_ids=(1302,)
    )
    names = {1301: "FIX-ING-ALPHA", 1302: "FIX-ING-BETA"}

    res = evaluate([med_alpha, med_beta], rules=[dose_threshold_rule], ingredient_names=names)
    assert res.interactions[0].severity_level == 2


def test_tc_dose_03_matching_unit_high_dose_triggers_threshold(dose_threshold_rule):
    """[TC-DOSE-03] Liều cao chuẩn đơn vị (80 mg >= 40 mg) -> Kích hoạt Severity 3."""
    med_alpha = EvaluatedMedication(
        medication_id=301,
        name="Fixture Drug Alpha",
        ingredient_ids=(1301,),
        dose_amount=80.0,
        dose_unit="mg",
    )
    med_beta = EvaluatedMedication(
        medication_id=302, name="Fixture Drug Beta", ingredient_ids=(1302,)
    )
    names = {1301: "FIX-ING-ALPHA", 1302: "FIX-ING-BETA"}

    res = evaluate([med_alpha, med_beta], rules=[dose_threshold_rule], ingredient_names=names)
    assert res.interactions[0].severity_level == 3
    expected_msg = dose_threshold_rule.dose_thresholds[0].warning_text
    assert res.interactions[0].warning_message == expected_msg


def test_tc_dose_04_matching_unit_low_dose_below_threshold(dose_threshold_rule):
    """[TC-DOSE-04] Liều thấp dưới ngưỡng (20 mg < 40 mg) -> Giữ Severity 2."""
    med_alpha = EvaluatedMedication(
        medication_id=301,
        name="Fixture Drug Alpha",
        ingredient_ids=(1301,),
        dose_amount=20.0,
        dose_unit="mg",
    )
    med_beta = EvaluatedMedication(
        medication_id=302, name="Fixture Drug Beta", ingredient_ids=(1302,)
    )
    names = {1301: "FIX-ING-ALPHA", 1302: "FIX-ING-BETA"}

    res = evaluate([med_alpha, med_beta], rules=[dose_threshold_rule], ingredient_names=names)
    assert res.interactions[0].severity_level == 2


# ==============================================================================
# PHÂN NHÓM 7: KHỬ TRÙNG LẶP & PHÁP LÝ DISCLAIMER
# ==============================================================================


def test_tc_dedup_01_shared_synthetic_ingredient():
    """[TC-DEDUP-01] Khử trùng lặp theo cặp thuốc khi nhiều biệt dược cùng mang 1 hoạt chất.

    - Brand 1 (ID 1) và Brand 2 (ID 2) cùng mang FIX-ING-SHARED (1401).
    - Partner (ID 3) mang FIX-ING-TARGET (1402).
    - Truyền rule tương tác lặp 2 lần để xác minh cơ chế deduplication: mỗi cặp thuốc
      chỉ sinh đúng 1 finding dù rule bị trùng lặp.
    - Evaluator sinh đúng 2 findings riêng: cặp (1, 3) và cặp (2, 3).
    - Không sinh finding giữa Brand 1 và Brand 2 (1, 2) vì cùng chia sẻ hoạt chất, không có rule.
    """
    med_brand1 = EvaluatedMedication(
        medication_id=1, name="Fixture Drug Brand 1", ingredient_ids=(1401,)
    )
    med_brand2 = EvaluatedMedication(
        medication_id=2, name="Fixture Drug Brand 2", ingredient_ids=(1401,)
    )
    med_partner = EvaluatedMedication(
        medication_id=3, name="Fixture Drug Partner", ingredient_ids=(1402,)
    )

    rule = _synthetic_rule(1401, 1402, sev=2, desc="Dedup test rule")
    names = {1401: "FIX-ING-SHARED", 1402: "FIX-ING-TARGET"}

    # Truyền rule lặp 2 lần để kiểm tra dedup trên từng cặp thuốc
    res = evaluate(
        [med_brand1, med_brand2, med_partner],
        rules=[rule, rule],
        ingredient_names=names,
    )

    # Đúng 2 findings độc lập cho 2 cặp thuốc thực tế, disclaimer NFR03
    assert res.status == CheckResult.FOUND
    assert len(res.interactions) == 2
    assert res.disclaimer == NFR03_DISCLAIMER

    # Thu thập các cặp medication ID phát hiện được
    med_pairs = {
        (
            min(f.medication_a_id, f.medication_b_id),
            max(f.medication_a_id, f.medication_b_id),
        )
        for f in res.interactions
    }
    # Kiểm tra chính xác 2 cặp (1, 3) và (2, 3)
    assert med_pairs == {(1, 3), (2, 3)}
    # Khẳng định không có finding giữa Brand 1 và Brand 2
    assert (1, 2) not in med_pairs


def test_tc_disc_01_disclaimer_mandatory_on_all_statuses():
    """[TC-DISC-01] Xác nhận disclaimer NFR03 xuất hiện ở mọi trạng thái kết quả."""
    med1 = EvaluatedMedication(medication_id=1, name="Med 1", ingredient_ids=(101,))
    med2 = EvaluatedMedication(medication_id=2, name="Med 2", ingredient_ids=(102,))
    med_unk = EvaluatedMedication(
        medication_id=3, name="Med Unk", ingredient_ids=(), has_interaction_data=False
    )

    rule = _synthetic_rule(101, 102, sev=2)

    # 1. FOUND (co_tuong_tac)
    res_found = evaluate([med1, med2], rules=[rule])
    assert res_found.disclaimer == NFR03_DISCLAIMER

    # 2. NONE_FOUND (da_kiem_tra_khong_thay)
    res_none = evaluate([med1, med2], rules=[])
    assert res_none.disclaimer == NFR03_DISCLAIMER

    # 3. INSUFFICIENT_DATA (khong_du_du_lieu)
    res_insuf = evaluate([med1, med_unk], rules=[])
    assert res_insuf.disclaimer == NFR03_DISCLAIMER


# ==============================================================================
# DRAFT-CONFORMANCE TESTS CHO 10 CA POSITIVE LÂM SÀNG (TASK 4.01 DRAFT RULES)
# ==============================================================================


@pytest.fixture
def draft_provisional_diabetes_rules():
    """10 quy tắc tương tác thuốc ĐTĐ dự thảo từ Task 4.01 (Sheet 30_TuongTacThuoc)."""
    return [
        # INT_DIA_001: Gliclazid (11) + Miconazol (15) -> Severity 4
        _synthetic_rule(
            11,
            15,
            itype=InteractionType.CONTRAINDICATED,
            sev=4,
            desc="Hạ glucose huyết nặng, hôn mê.",
        ),
        # INT_DIA_002: Glibenclamid (12) + Bosentan (16) -> Severity 4
        _synthetic_rule(
            12,
            16,
            itype=InteractionType.CONTRAINDICATED,
            sev=4,
            desc="Tổn thương gan, giảm hiệu quả.",
        ),
        # INT_DIA_003: Metformin (10) + Iod (17) -> Severity 4
        _synthetic_rule(
            10,
            17,
            itype=InteractionType.CONTRAINDICATED,
            sev=4,
            desc="Suy thận cấp, toan lactic.",
        ),
        # INT_DIA_004: Gliclazid (11) + Fluconazol (18) -> Severity 3
        _synthetic_rule(
            11,
            18,
            itype=InteractionType.DOSE_DEPENDENT,
            sev=3,
            desc="Ức chế CYP2C9, hạ đường huyết quá mức.",
        ),
        # INT_DIA_005: Metformin (10) + Cimetidin (19) -> Severity 2
        _synthetic_rule(
            10,
            19,
            itype=InteractionType.DOSE_DEPENDENT,
            sev=2,
            desc="Cạnh tranh bài tiết OCT2 ống thận.",
        ),
        # INT_DIA_006: Insulin (14) + Propranolol (20) -> Severity 3
        _synthetic_rule(
            14,
            20,
            itype=InteractionType.DOSE_DEPENDENT,
            sev=3,
            desc="Che lấp triệu chứng hạ đường huyết.",
        ),
        # INT_DIA_007: Metformin (10) + Furosemid (21) -> Severity 2
        _synthetic_rule(
            10,
            21,
            itype=InteractionType.DOSE_DEPENDENT,
            sev=2,
            desc="Giảm thể tích dịch tuần hoàn, suy thận.",
        ),
        # INT_DIA_008: Gliclazid (11) + Prednisolon (22) -> Severity 3
        _synthetic_rule(
            11,
            22,
            itype=InteractionType.DOSE_DEPENDENT,
            sev=3,
            desc="Glucocorticoid đối kháng tác dụng.",
        ),
        # INT_DIA_009: Glibenclamid (12) + Ciprofloxacin (23) -> Severity 3
        _synthetic_rule(
            12,
            23,
            itype=InteractionType.DOSE_DEPENDENT,
            sev=3,
            desc="Quinolon tăng tác dụng hạ glucose huyết sâu.",
        ),
        # INT_DIA_010: Glimepirid (13) + Clarithromycin (24) -> Severity 3
        _synthetic_rule(
            13,
            24,
            itype=InteractionType.DOSE_DEPENDENT,
            sev=3,
            desc="Macrolid ức chế CYP3A4.",
        ),
    ]


@pytest.mark.parametrize(
    "case_id, cand_id, cand_ing, exist_id, exist_ing, expected_sev",
    [
        ("TC-POS-01", 11, 11, 15, 15, 4),  # Gliclazid + Miconazol
        ("TC-POS-02", 12, 12, 16, 16, 4),  # Glibenclamid + Bosentan
        ("TC-POS-03", 10, 10, 17, 17, 4),  # Metformin + Iod
        ("TC-POS-04", 11, 11, 18, 18, 3),  # Gliclazid + Fluconazol
        ("TC-POS-05", 10, 10, 19, 19, 2),  # Metformin + Cimetidin
        ("TC-POS-06", 14, 14, 20, 20, 3),  # Insulin + Propranolol
        ("TC-POS-07", 10, 10, 21, 21, 2),  # Metformin + Furosemid
        ("TC-POS-08", 11, 11, 22, 22, 3),  # Gliclazid + Prednisolon
        ("TC-POS-09", 12, 12, 23, 23, 3),  # Glibenclamid + Ciprofloxacin
        ("TC-POS-10", 13, 13, 24, 24, 3),  # Glimepirid + Clarithromycin
    ],
)
def test_draft_conformance_positive_cases(
    draft_provisional_diabetes_rules,
    case_id,
    cand_id,
    cand_ing,
    exist_id,
    exist_ing,
    expected_sev,
):
    """Draft-conformance test cho 10 ca dương tính lâm sàng Task 4.01.

    LƯU Ý: Đây chỉ là kiểm tra độ khớp logic với bản nháp dữ liệu provisional,
    KHÔNG dùng để tuyên bố True Positive lâm sàng vì chưa có Dược sĩ ký duyệt.
    """
    cand = EvaluatedMedication(
        medication_id=cand_id, name=f"Drug {cand_id}", ingredient_ids=(cand_ing,)
    )
    exist = EvaluatedMedication(
        medication_id=exist_id, name=f"Drug {exist_id}", ingredient_ids=(exist_ing,)
    )

    res = evaluate([cand, exist], rules=draft_provisional_diabetes_rules)

    assert res.status == CheckResult.FOUND, f"Failed on {case_id}"
    assert len(res.interactions) == 1, f"Failed on {case_id}"
    assert res.interactions[0].severity_level == expected_sev, f"Failed on {case_id}"
    assert res.disclaimer == NFR03_DISCLAIMER


# ==============================================================================
# DRAFT-CONFORMANCE TESTS CHO 5 CA NEGATIVE CANDIDATE TỪ PHÁC ĐỒ ĐIỀU TRỊ
# ==============================================================================


@pytest.mark.parametrize(
    "case_id, cand_id, cand_ing, exist_id, exist_ing",
    [
        ("TC-NEG-01", 10, 10, 11, 11),  # Metformin + Gliclazid
        ("TC-NEG-02", 10, 10, 13, 13),  # Metformin + Glimepirid
        ("TC-NEG-03", 10, 10, 14, 14),  # Metformin + Insulin
        ("TC-NEG-04", 10, 10, 25, 25),  # Metformin + Amlodipin
        ("TC-NEG-05", 10, 10, 26, 26),  # Metformin + Paracetamol
    ],
)
def test_draft_conformance_negative_candidates(
    draft_provisional_diabetes_rules, case_id, cand_id, cand_ing, exist_id, exist_ing
):
    """Draft-conformance test cho 5 ca candidate âm tính theo phác đồ điều trị.

    LƯU Ý: Đây là ca ứng viên từ hướng dẫn điều trị, KHÔNG PHẢI True-Negative Oracle
    và TUYỆT ĐỐI KHÔNG dùng để tính tỷ lệ False Positive.
    """
    cand = EvaluatedMedication(
        medication_id=cand_id, name=f"Drug {cand_id}", ingredient_ids=(cand_ing,)
    )
    exist = EvaluatedMedication(
        medication_id=exist_id, name=f"Drug {exist_id}", ingredient_ids=(exist_ing,)
    )

    res = evaluate([cand, exist], rules=draft_provisional_diabetes_rules)

    assert res.status == CheckResult.NONE_FOUND, f"Failed on {case_id}"
    assert len(res.interactions) == 0, f"Failed on {case_id}"
    assert res.disclaimer == NFR03_DISCLAIMER
