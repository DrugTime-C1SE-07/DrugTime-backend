"""Unit test cho scripts/build_knowledge_seed.py (task 4.04: AC1–AC4, AC10, AC14, AC15)."""

import importlib.util
import sys
from pathlib import Path

import pytest

openpyxl = pytest.importorskip("openpyxl")

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "build_knowledge_seed.py"
_spec = importlib.util.spec_from_file_location("build_knowledge_seed", SCRIPT)
seed = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = seed
_spec.loader.exec_module(seed)

PAGE = "DTQGVN 2018 tr. 100"

HEADERS = {
    "10_NhomBenh": ["Mã nhóm *\n[code]", "Tên nhóm *\n[name]", "Đang dùng\n[is_active]"],
    "20_HoatChat": [
        "Tên chuẩn *\n[standard_name]",
        "Vai trò *\n[role]",
        "Nhóm\n[pharmacological_group]",
        "ATC\n[atc_code]",
        "Nguồn\n[source]",
        "Vị trí trong nguồn\n[không nạp DB]",
        "Số alias\n[tự tính]",
    ],
    "21_AliasHoatChat": [
        "Hoạt chất *\n[active_ingredient_id]",
        "Alias *\n[alias_text]",
        "Vị trí trong nguồn\n[không nạp DB]",
    ],
    "22_HoatChat_NhomBenh": [
        "Hoạt chất *\n[active_ingredient_id]",
        "Mã nhóm *\n[disease_group_id]",
    ],
    "23_NhomDuocLy": ["Tên nhóm *\n[class_name]", "Nguồn\n[source]"],
    "24_HoatChat_NhomDuocLy": [
        "Hoạt chất *\n[active_ingredient_id]",
        "Nhóm thuốc *\n[drug_class_id]",
    ],
    "30_TuongTacThuoc": [
        "Mã tạm\n[không nạp DB]",
        "A *\n[ingredient_a_id]",
        "B có? *\n[ingredient_b_in_table_a]",
        "B\n[ingredient_b_id]",
        "B ngoài\n[ingredient_b_external_name]",
        "Loại *\n[interaction_type]",
        "Mức *\n[severity_level]",
        "Xử lý *\n[handling_type]",
        "Giờ\n[min_interval_hours]",
        "Mô tả *\n[description]",
        "Nguồn *\n[source]",
        "Xác minh *\n[verification_status]",
    ],
    "31_NguongLieu": [
        "Mã tạm tương tác *\n[interaction_id]",
        "Áp cho *\n[ingredient_ref]",
        "Liều tối thiểu\n[min_dose]",
        "Liều tối đa\n[max_dose]",
        "Đơn vị liều *\n[dose_unit]",
        "Mức *\n[severity_level]",
        "Cảnh báo *\n[warning_text]",
        "Vị trí trong nguồn\n[không nạp DB]",
    ],
    "32_TuongTacThucAn": [
        "Hoạt chất *\n[active_ingredient_id]",
        "Thực phẩm *\n[food_to_avoid]",
        "Mức *\n[severity_level]",
        "Lý do *\n[reason]",
        "Nguồn *\n[source]",
        "Xác minh *\n[verification_status]",
    ],
    "34_DoPhuRaSoat": [
        "Hoạt chất *\n[active_ingredient_id]",
        "Đã rà thuốc–thuốc *\n[không nạp DB]",
        "Đã rà thức ăn *\n[không nạp DB]",
        "Kết quả thức ăn *\n[không nạp DB]",
        "Trang đã đọc *\n[không nạp DB]",
        "Trạng thái xác minh *\n[không nạp DB]",
    ],
    "40_BietDuoc": [
        "Mã tạm\n[không nạp DB]",
        "Tên thuốc *\n[name]",
        "Hoạt chất\n[raw_active_ingredient]",
        "Hàm lượng\n[strength_text]",
        "Dạng\n[dosage_form]",
        "NSX\n[manufacturer_name]",
        "Nước\n[manufacturer_country]",
        "Đóng gói\n[packaging_spec]",
        "Nguồn\n[source]",
        "Mã ở nguồn\n[source_ref]",
        "Vị trí trong nguồn\n[không nạp DB]",
    ],
    "41_BietDuoc_HoatChat": [
        "Mã tạm *\n[medication_id]",
        "Hoạt chất *\n[active_ingredient_id]",
        "Hàm lượng *\n[strength_value]",
        "Đơn vị *\n[strength_unit]",
        "Định lượng *\n[dosing_unit]",
    ],
}


def _base():
    """Workbook hợp lệ nhỏ nhất: 3 hoạt chất, 2 thuốc (1 phối hợp), 1 cặp thuốc, 2 quy tắc ăn."""
    return {
        "10_NhomBenh": [["dtd", "Đái tháo đường", True]],
        "20_HoatChat": [
            ["Alpha", "dieu_tri_benh_nen", "Nhóm A", "A01", "DTQGVN 2018", PAGE, "=1"],
            ["Beta", "trieu_chung_cap_tinh", None, None, "DTQGVN 2018", PAGE, "=1"],
            ["Gamma", "trieu_chung_cap_tinh", None, None, "DTQGVN 2018", PAGE, "=1"],
        ],
        "21_AliasHoatChat": [
            ["Alpha", "Alphine", PAGE],
            ["Beta", "Betaine", PAGE],
            ["Gamma", "Gammol", PAGE],
        ],
        "22_HoatChat_NhomBenh": [["Alpha", "dtd"]],
        "23_NhomDuocLy": [],
        "24_HoatChat_NhomDuocLy": [],
        "30_TuongTacThuoc": [
            [
                "I1",
                "Alpha",
                "co",
                "Beta",
                None,
                "chong_chi_dinh",
                4,
                "tranh_phoi_hop",
                None,
                "Mô tả 'có nháy'",
                "DTQGVN 2018, tr. 10",
                "da_xac_minh",
            ],
        ],
        "31_NguongLieu": [],
        "32_TuongTacThucAn": [
            ["Alpha", "Rượu", 3, "Lý do 1", "DTQGVN 2018, tr. 11", "da_xac_minh"],
            ["Alpha", "Nước bưởi", 2, "Lý do 2", "DTQGVN 2018, tr. 12", "da_xac_minh"],
        ],
        "34_DoPhuRaSoat": [
            ["Alpha", "co", "co", "co_quy_tac", "tr. 10–12", "da_xac_minh"],
            ["Beta", "co", "co", "khong_thay", "tr. 20", "da_xac_minh"],
            ["Gamma", "co", "co", "khong_thay", "tr. 30", "da_xac_minh"],
        ],
        "40_BietDuoc": [
            [
                "M1",
                "Alphadol 500",
                "Alpha",
                "500 mg",
                "Viên nén",
                None,
                None,
                None,
                None,
                None,
                PAGE,
            ],
            [
                "M2",
                "BetaGam",
                "Beta, Gamma",
                "10 mg + 2,5 mg",
                "Viên nén",
                None,
                None,
                None,
                None,
                None,
                PAGE,
            ],
        ],
        "41_BietDuoc_HoatChat": [
            ["M1", "Alpha", 500, "mg", "viên"],
            ["M2", "Beta", 10, "mg", "viên"],
            ["M2", "Gamma", 2.5, "mg", "viên"],
        ],
    }


RULES_FINAL = [
    ["QUY ƯỚC"],
    ["1. Thang mức độ severity_level (1–4)"],
    ["Mức", "Tên gọi"],
    [1, "Nhẹ"],
    [2, "Thận trọng"],
    [3, "Tránh"],
    [4, "Chống chỉ định"],
    ["2. Giá trị verification_status"],
    ["3. Đơn vị hàm lượng / đơn vị liều (strength_unit, dose_unit)"],
    ["Dùng cho medication_active_ingredients.strength_unit và ngưỡng liều dose_unit."],
    ["Đơn vị (ghi đúng y như sẽ nạp DB)", "Đơn vị gốc quy đổi"],
    ["mg", "mg"],
    ["g", "mg"],
    ["CHƯA KHAI BÁO", "—"],
    ["4. Đơn vị định lượng mỗi lần dùng (dosing_unit)"],
    ["viên"],
    ["9. Người duyệt (QD-37)"],
    ["Rà soát nguồn", "Đức", "07/11/2026"],
    ["Dược sĩ duyệt nội dung", "DS-01", "07/11/2026"],
    ["Phát hành", "Nguyên", "07/11/2026"],
]


def _write(tmp_path, data=None, rules=None, name="wb.xlsx"):
    data = _base() if data is None else data
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "02_QuyUoc"
    for row in rules if rules is not None else RULES_FINAL:
        ws.append(row)
    for sheet, headers in HEADERS.items():
        s = wb.create_sheet(sheet)
        s.append([f"{sheet} → bảng"])
        s.append(headers)
        s.append(["mô tả"] * len(headers))
        for row in data.get(sheet, []):
            s.append(row)
    path = tmp_path / name
    wb.save(path)
    return path


def _build(tmp_path, **kw):
    return seed.build(_write(tmp_path, **kw))


def _errors_contain(result, text):
    assert any(text in e for e in result.errors), result.errors


def test_valid_minimal_workbook_builds_sql(tmp_path):
    r = _build(tmp_path)
    assert r.errors == []
    assert "-- count active_ingredients=3" in r.sql
    assert "-- count drug_food_interactions=2" in r.sql
    assert "-- count medication_active_ingredients=3" in r.sql
    assert "'da_xac_minh'" in r.sql
    assert "2.5" in r.sql and "2.50" not in r.sql


def test_sql_escapes_quotes(tmp_path):
    r = _build(tmp_path)
    assert "'Mô tả ''có nháy'''" in r.sql


@pytest.mark.parametrize(
    "sheet,index,col",
    [
        ("21_AliasHoatChat", 0, 0),
        ("22_HoatChat_NhomBenh", 0, 0),
        ("30_TuongTacThuoc", 0, 3),
        ("32_TuongTacThucAn", 0, 0),
        ("41_BietDuoc_HoatChat", 0, 1),
    ],
)
def test_unknown_ingredient_reference_fails__AC1(tmp_path, sheet, index, col):
    data = _base()
    data[sheet][index][col] = "Không tồn tại"
    r = _build(tmp_path, data=data)
    _errors_contain(r, "'Không tồn tại' không có")
    assert r.sql == ""


def test_severity_out_of_range_and_bad_enum_fail__AC1(tmp_path):
    data = _base()
    data["30_TuongTacThuoc"][0][6] = 5
    data["30_TuongTacThuoc"][0][7] = "ngung_thuoc"
    data["32_TuongTacThucAn"][0][2] = 0
    r = _build(tmp_path, data=data)
    _errors_contain(r, "30_TuongTacThuoc dòng 4: severity_level phải là số nguyên 1–4")
    _errors_contain(r, "32_TuongTacThucAn dòng 4: severity_level phải là số nguyên 1–4")
    _errors_contain(r, "handling_type='ngung_thuoc'")


def test_verified_row_without_page_fails__AC1(tmp_path):
    data = _base()
    data["32_TuongTacThucAn"][1][4] = "DTQGVN 2018"
    r = _build(tmp_path, data=data)
    _errors_contain(r, "32_TuongTacThucAn dòng 5: 'source' phải có số trang")


def test_unverified_row_without_page_is_not_an_error(tmp_path):
    data = _base()
    data["32_TuongTacThucAn"][1][4] = "DTQGVN 2018"
    data["32_TuongTacThucAn"][1][5] = "pending_review"
    assert _build(tmp_path, data=data).errors == []


def test_duplicate_pair_both_directions_and_duplicate_food_fail__AC1(tmp_path):
    data = _base()
    data["30_TuongTacThuoc"].append(
        [
            "I2",
            "Beta",
            "co",
            "Alpha",
            None,
            "chong_chi_dinh",
            2,
            "can_theo_doi",
            None,
            "x",
            "tr. 1",
            "da_xac_minh",
        ]
    )
    data["32_TuongTacThucAn"].append(["Alpha", "rượu", 1, "x", "tr. 1", "da_xac_minh"])
    r = _build(tmp_path, data=data)
    _errors_contain(r, "30_TuongTacThuoc dòng 5: trùng cặp")
    _errors_contain(r, "32_TuongTacThucAn dòng 6: trùng thực phẩm")


def _base_dose():
    """Như _base() nhưng I1 là phu_thuoc_lieu (quy tắc có ngưỡng liều phải thuộc loại này)."""
    data = _base()
    data["30_TuongTacThuoc"][0][5] = "phu_thuoc_lieu"
    return data


def _threshold(code="I1", ref="B", lo=None, hi=199, unit="mg", sev=3, text="Cảnh báo", loc=PAGE):
    return [code, ref, lo, hi, unit, sev, text, loc]


@pytest.mark.parametrize(
    "row,expected",
    [
        (_threshold(code="I9"), "mã tạm tương tác 'I9' không có"),
        (_threshold(ref="C"), "ingredient_ref='C'"),
        (_threshold(lo=None, hi=None), "phải có ít nhất một trong min_dose/max_dose"),
        (_threshold(lo=-1, hi=None), "min_dose phải là số ≥ 0"),
        (_threshold(lo=300, hi=200), "min_dose lớn hơn max_dose"),
        (_threshold(unit="viên"), "dose_unit 'viên' không thuộc"),
        (_threshold(sev=5), "severity_level phải là số nguyên 1–4"),
        (_threshold(text=None), "thiếu 'warning_text'"),
        (_threshold(loc="Sách TT 2015"), "'Vị trí trong nguồn' phải có số trang"),
    ],
)
def test_dose_threshold_invalid_rows_fail__AC16(tmp_path, row, expected):
    data = _base_dose()
    data["31_NguongLieu"] = [row]
    r = _build(tmp_path, data=data)
    _errors_contain(r, expected)
    assert r.sql == ""


def test_dose_thresholds_seeded_with_parent_rule__AC16(tmp_path):
    data = _base_dose()
    data["31_NguongLieu"] = [
        _threshold(lo=200, hi=None, sev=4, text="Liều cao"),
        _threshold(lo=None, hi=199, sev=3, text="Liều thấp"),
    ]
    r = _build(tmp_path, data=data)
    assert r.errors == []
    assert "-- count active_ingredient_interaction_dose_thresholds=2" in r.sql
    body = r.sql.split("BEGIN;", 1)[1]
    assert body.rstrip().endswith("COMMIT;")
    assert body.index("INSERT INTO active_ingredient_interactions") < body.index(
        "INSERT INTO active_ingredient_interaction_dose_thresholds"
    )
    # Khoảng mở dưới đứng trước; nối theo cặp tên chuẩn của quy tắc cha, chỉ version hiện hành.
    assert body.index("'Liều thấp'") < body.index("'Liều cao'")
    assert "('Alpha', 'Beta', 'B', NULL, 199, 'mg', 3, 'Liều thấp')" in body
    assert "i.superseded_at IS NULL AND i.deleted_at IS NULL" in body


@pytest.mark.parametrize("change", ["pending", "external"])
def test_dose_thresholds_skipped_when_parent_skipped__AC16(tmp_path, change):
    data = _base_dose()
    if change == "pending":
        data["30_TuongTacThuoc"][0][11] = "pending_review"
    else:
        data["30_TuongTacThuoc"][0][2:5] = ["khong", None, "Thuốc ngoài danh mục"]
    data["31_NguongLieu"] = [_threshold()]
    r = _build(tmp_path, data=data)
    assert r.errors == []
    assert "-- count active_ingredient_interaction_dose_thresholds=0" in r.sql
    assert "[quy_tac_cha_bi_bo] 31_NguongLieu dòng 4: I1 B mg" in r.report


@pytest.mark.parametrize(
    "rows,overlap",
    [
        ([(None, 199), (200, None)], False),
        ([(None, 200), (200, None)], True),
        ([(100, 300), (200, 250)], True),
        ([(200, None), (300, None)], True),
        ([(None, 100), (150, 199), (200, None)], False),
    ],
)
def test_open_ended_ranges_overlap_detected__AC16(tmp_path, rows, overlap):
    data = _base_dose()
    data["31_NguongLieu"] = [_threshold(lo=lo, hi=hi) for lo, hi in rows]
    r = _build(tmp_path, data=data)
    assert any("khoảng liều chồng" in e for e in r.errors) is overlap, r.errors


def test_threshold_requires_dose_dependent_parent__AC16(tmp_path):
    data = _base()  # I1 là chong_chi_dinh
    data["31_NguongLieu"] = [_threshold()]
    _errors_contain(_build(tmp_path, data=data), "interaction_type không phải phu_thuoc_lieu")


def test_duplicate_drug_rule_code_fails__AC16(tmp_path):
    data = _base()
    data["30_TuongTacThuoc"].append(
        [
            "I1",
            "Alpha",
            "co",
            "Gamma",
            None,
            "chong_chi_dinh",
            2,
            "can_theo_doi",
            None,
            "x",
            "tr. 1",
            "da_xac_minh",
        ]
    )
    _errors_contain(_build(tmp_path, data=data), "trùng mã tạm 'I1'")


def test_medication_with_catalog_source_rejected__AC1(tmp_path):
    data = _base()
    data["40_BietDuoc"][0][8] = "dav_drugbank"
    _errors_contain(_build(tmp_path, data=data), "phải để trống source/source_ref")


def test_errors_write_no_file_and_exit_1__AC1(tmp_path, capsys):
    data = _base()
    data["30_TuongTacThuoc"][0][6] = 9
    out = tmp_path / "seed.sql"
    code = seed.main([str(_write(tmp_path, data=data)), "--out", str(out)])
    assert code == 1
    assert not out.exists()
    assert "severity_level" in capsys.readouterr().err


def test_cli_writes_sql_and_report(tmp_path):
    out, report = tmp_path / "seed.sql", tmp_path / "report.txt"
    code = seed.main([str(_write(tmp_path)), "--out", str(out), "--report", str(report)])
    assert code == 0
    assert out.read_text(encoding="utf-8").startswith("-- FILE SINH TỰ ĐỘNG")
    assert "active_ingredients: 3" in report.read_text(encoding="utf-8")


def test_skips_rules_not_verified__AC2(tmp_path):
    data = _base()
    data["30_TuongTacThuoc"][0][11] = "pending_review"
    data["32_TuongTacThucAn"][1][5] = "pending_review"
    r = _build(tmp_path, data=data)
    assert r.errors == []
    assert "-- count active_ingredient_interactions=0" in r.sql
    assert "-- count drug_food_interactions=1" in r.sql
    assert "Nước bưởi" not in r.sql
    assert "[chua_xac_minh] 30_TuongTacThuoc dòng 4: I1" in r.report
    assert "[chua_xac_minh] 32_TuongTacThucAn dòng 5: Alpha – Nước bưởi" in r.report


def test_skips_ingredient_with_unapproved_coverage_and_its_medications__AC2(tmp_path):
    data = _base()
    data["34_DoPhuRaSoat"][2][5] = "pending_review"  # Gamma
    r = _build(tmp_path, data=data)
    assert r.errors == []
    assert "-- count active_ingredients=2" in r.sql
    assert "'Gamma'" not in r.sql and "'Gammol'" not in r.sql
    # Thuốc phối hợp Beta + Gamma bị bỏ cả thuốc, không seed thuốc thiếu thành phần.
    assert "BetaGam" not in r.sql
    assert "[hoat_chat_chua_duyet_do_phu] 20_HoatChat dòng 6: Gamma" in r.report
    assert "[thuoc_co_hoat_chat_bi_bo] 40_BietDuoc dòng 5: BetaGam" in r.report


def test_output_byte_identical_twice__AC3(tmp_path):
    path = _write(tmp_path)
    assert seed.build(path).sql == seed.build(path).sql
    reordered = _base()
    reordered["32_TuongTacThucAn"].reverse()
    reordered["20_HoatChat"].reverse()
    other = seed.build(_write(tmp_path, data=reordered, name="other.xlsx"))

    def body(sql: str) -> list[str]:  # bỏ dòng sha256 vì hai file workbook khác nhau
        return [line for line in sql.splitlines() if not line.startswith("-- workbook sha256")]

    assert body(other.sql) == body(seed.build(path).sql)


def test_missing_coverage_fails__AC4(tmp_path):
    data = _base()
    data["34_DoPhuRaSoat"].pop()  # Gamma
    _errors_contain(_build(tmp_path, data=data), "thiếu dòng độ phủ cho 'Gamma' (G11)")


def test_coverage_without_page_or_inconsistent_fails__AC4(tmp_path):
    data = _base()
    data["34_DoPhuRaSoat"][1][4] = "đã đọc"
    data["34_DoPhuRaSoat"][0][3] = "khong_thay"
    r = _build(tmp_path, data=data)
    _errors_contain(r, "34_DoPhuRaSoat dòng 5: 'Trang đã đọc' phải có số trang")
    _errors_contain(r, "34_DoPhuRaSoat dòng 4: ghi 'khong_thay' nhưng có quy tắc thức ăn")


def test_requires_reviewer_roles_and_final_scale__AC10(tmp_path):
    rules = [list(r) for r in RULES_FINAL]
    rules[rules.index([1, "Nhẹ"])] = [1, "Nhẹ (dự thảo)"]
    pharmacist = next(i for i, r in enumerate(rules) if r[0] == "Dược sĩ duyệt nội dung")
    rules[pharmacist] = ["Dược sĩ duyệt nội dung", None, None]
    r = _build(tmp_path, rules=rules)
    _errors_contain(r, "thang mức độ mức 1 còn ghi 'dự thảo'")
    _errors_contain(r, "thiếu người hoặc ngày duyệt cho vai trò 'Dược sĩ duyệt nội dung'")


def test_skips_external_b_and_unlinked_class__AC14(tmp_path):
    data = _base()
    data["30_TuongTacThuoc"].append(
        [
            "I3",
            "Alpha",
            "khong",
            None,
            "Thuốc cản quang chứa Iod",
            "chong_chi_dinh",
            4,
            "tranh_phoi_hop",
            None,
            "x",
            "tr. 956",
            "da_xac_minh",
        ]
    )
    data["23_NhomDuocLy"] = [["Thuốc cản quang chứa Iod", "DTQGVN 2018"], ["Nhóm có gắn", None]]
    data["24_HoatChat_NhomDuocLy"] = [["Alpha", "Nhóm có gắn"]]
    r = _build(tmp_path, data=data)
    assert r.errors == []
    assert "cản quang" not in r.sql
    assert "-- count drug_classes=1" in r.sql
    assert "[b_ngoai_danh_muc] 30_TuongTacThuoc dòng 5: I3" in r.report
    assert "[nhom_khong_gan_hoat_chat] 23_NhomDuocLy dòng 4: Thuốc cản quang chứa Iod" in r.report


@pytest.mark.parametrize(
    "sheet,expected",
    [
        ("21_AliasHoatChat", "'Alpha' chưa có alias"),
        ("22_HoatChat_NhomBenh", "'Alpha' (dieu_tri_benh_nen) chưa gắn nhóm bệnh"),
    ],
)
def test_new_ingredients_complete__AC15(tmp_path, sheet, expected):
    data = _base()
    data[sheet] = [r for r in data[sheet] if r[0] != "Alpha"]
    _errors_contain(_build(tmp_path, data=data), expected)


def test_ingredient_without_medication_or_page_fails__AC15(tmp_path):
    data = _base()
    data["41_BietDuoc_HoatChat"] = [r for r in data["41_BietDuoc_HoatChat"] if r[0] != "M1"]
    data["40_BietDuoc"] = [r for r in data["40_BietDuoc"] if r[0] != "M1"]
    data["20_HoatChat"][1][5] = "file.md"
    r = _build(tmp_path, data=data)
    _errors_contain(r, "'Alpha' chưa có thuốc mẫu")
    _errors_contain(r, "20_HoatChat dòng 5: 'Vị trí trong nguồn' phải có số trang")


def test_missing_sheet_reported(tmp_path):
    path = _write(tmp_path)
    wb = openpyxl.load_workbook(path)
    del wb["34_DoPhuRaSoat"]
    wb.save(path)
    _errors_contain(seed.build(path), "Thiếu sheet: 34_DoPhuRaSoat")
