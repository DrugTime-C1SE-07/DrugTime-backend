"""Sinh seed SQL cho kho tri thức dược từ workbook dữ liệu (task 4.04).

Dùng:
    python scripts/build_knowledge_seed.py <workbook.xlsx> \
        --out supabase/seeds/10_knowledge_base.sql [--report report.txt]

Workbook theo mẫu "DrugTime_DuLieuDuoc" (bám schema v11): dòng 2 là tiêu đề cột dạng
"Nhãn *\\n[ten_cot_db]", dữ liệu bắt đầu từ dòng 4. Script:

1. kiểm ràng buộc (khóa tham chiếu, enum, mức độ 1–4, trích dẫn có số trang, trùng lặp, độ phủ
   rà soát G11, vai trò duyệt QD-37); có lỗi thì in ra stderr, exit 1, không ghi file;
2. lọc: chỉ quy tắc ``da_xac_minh``; hoạt chất phải có dòng độ phủ đã duyệt; bỏ quy tắc mà engine
   không khớp được (B ngoài danh mục) và nhóm thuốc không gắn hoạt chất;
3. sinh SQL tất định (cùng workbook → cùng byte), không chứa thời điểm sinh.

Engine không lọc ``verification_status`` khi đọc quy tắc, nên bước lọc ở đây là cổng chặn dữ liệu
chưa duyệt đến người dùng.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path

VERIFIED = "da_xac_minh"
ROLES = {"dieu_tri_benh_nen", "trieu_chung_cap_tinh"}
YES_NO = {"co", "khong"}
INTERACTION_TYPES = {"chong_chi_dinh", "phu_thuoc_lieu"}
HANDLING_TYPES = {"tranh_phoi_hop", "can_theo_doi", "cach_gio", "giam_lieu"}
FOOD_RESULTS = {"co_quy_tac", "khong_thay"}
REVIEW_ROLES = ("Rà soát nguồn", "Dược sĩ duyệt nội dung", "Phát hành")
PAGE_RE = re.compile(r"\btr\.\s*\d+", re.IGNORECASE)
HEADER_RE = re.compile(r"\[([a-z_]+)\]")
FIRST_DATA_ROW = 4

SHEETS = {
    "rules": "02_QuyUoc",
    "groups": "10_NhomBenh",
    "ingredients": "20_HoatChat",
    "aliases": "21_AliasHoatChat",
    "ingredient_groups": "22_HoatChat_NhomBenh",
    "classes": "23_NhomDuocLy",
    "ingredient_classes": "24_HoatChat_NhomDuocLy",
    "drug": "30_TuongTacThuoc",
    "thresholds": "31_NguongLieu",
    "food": "32_TuongTacThucAn",
    "coverage": "34_DoPhuRaSoat",
    "meds": "40_BietDuoc",
    "med_ingredients": "41_BietDuoc_HoatChat",
}

SKIP_NOT_VERIFIED = "chua_xac_minh"
SKIP_EXTERNAL_B = "b_ngoai_danh_muc"
SKIP_UNLINKED_CLASS = "nhom_khong_gan_hoat_chat"
SKIP_INGREDIENT = "hoat_chat_chua_duyet_do_phu"
SKIP_MEDICATION = "thuoc_co_hoat_chat_bi_bo"
SKIP_PARENT = "quy_tac_cha_bi_bo"


@dataclass
class Row:
    sheet: str
    number: int
    values: dict[str, object]

    def text(self, key: str) -> str:
        value = self.values.get(key)
        return "" if value is None else str(value).strip()

    @property
    def where(self) -> str:
        return f"{self.sheet} dòng {self.number}"


@dataclass
class BuildResult:
    sql: str = ""
    report: str = ""
    errors: list[str] = field(default_factory=list)


def _column_key(header: object) -> str | None:
    if header is None:
        return None
    text = str(header)
    match = HEADER_RE.search(text)
    if match:
        return match.group(1)
    label = text.split("\n", 1)[0].replace("*", "").strip()
    return label or None


def _read_sheet(wb, name: str) -> list[Row]:
    ws = wb[name]
    raw_headers = next(ws.iter_rows(min_row=2, max_row=2, values_only=True))
    # Cột "[tự tính]" là công thức kiểm tra của workbook, không phải dữ liệu.
    columns = [
        (i, _column_key(h))
        for i, h in enumerate(raw_headers)
        if _column_key(h) is not None and "[tự tính]" not in str(h)
    ]
    rows: list[Row] = []
    for number, cells in enumerate(
        ws.iter_rows(min_row=FIRST_DATA_ROW, max_col=len(raw_headers), values_only=True),
        start=FIRST_DATA_ROW,
    ):
        values: dict[str, object] = {}
        for i, key in columns:
            value = cells[i] if i < len(cells) else None
            if isinstance(value, str):
                value = value.strip() or None
            values.setdefault(key, value)
        if any(v is not None for v in values.values()):
            rows.append(Row(name, number, values))
    return rows


def _number(value: object) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return Decimal(str(value).replace(",", "."))
    except InvalidOperation:
        return None


def _fmt_number(value: Decimal) -> str:
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def _sql(value: object) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, Decimal):
        return _fmt_number(value)
    if isinstance(value, int):
        return str(value)
    return "'" + str(value).replace("'", "''") + "'"


def _values(rows: list[tuple]) -> str:
    return ",\n".join("    (" + ", ".join(_sql(v) for v in r) + ")" for r in rows)


def _check_rules_sheet(wb, errors: list[str]) -> set[str]:
    """Kiểm thang mức độ và vai trò duyệt; trả về danh sách đơn vị ở mục 3 (dose_unit hợp lệ)."""
    ws = wb[SHEETS["rules"]]
    scale_rows: list[tuple] = []
    roles: dict[str, tuple] = {}
    units: set[str] = set()
    section = ""
    for row in ws.iter_rows(values_only=True):
        first = "" if not row or row[0] is None else str(row[0]).strip()
        heading = re.match(r"^(\d+)\.\s", first)
        if heading:
            section = heading.group(1)
            continue
        if section == "1" and first in {"1", "2", "3", "4"}:
            scale_rows.append(row)
        # Mục 3: mỗi đơn vị một dòng ở cột A (mg, g, mcg…); bỏ dòng mô tả, tiêu đề cột và
        # dòng "CHƯA KHAI BÁO" (viết hoa toàn bộ).
        if section == "3" and first and " " not in first and first.upper() != first:
            units.add(first)
        if first in REVIEW_ROLES:
            roles[first] = row
    if len(scale_rows) != 4:
        errors.append(f"{SHEETS['rules']}: không tìm thấy đủ 4 mức của thang mức độ")
    for row in scale_rows:
        if "dự thảo" in " ".join(str(c) for c in row if c is not None).lower():
            errors.append(f"{SHEETS['rules']}: thang mức độ mức {row[0]} còn ghi 'dự thảo'")
    for role in REVIEW_ROLES:
        row = roles.get(role)
        if row is None or len(row) < 3 or not row[1] or not row[2]:
            errors.append(f"{SHEETS['rules']}: thiếu người hoặc ngày duyệt cho vai trò '{role}'")
    return units


def build(workbook_path: Path) -> BuildResult:
    from openpyxl import load_workbook

    data = Path(workbook_path).read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    wb = load_workbook(workbook_path, data_only=False)
    result = BuildResult()
    errors = result.errors

    missing = [s for s in SHEETS.values() if s not in wb.sheetnames]
    if missing:
        errors.append("Thiếu sheet: " + ", ".join(missing))
        return result

    dose_units = _check_rules_sheet(wb, errors)
    sheet = {key: _read_sheet(wb, name) for key, name in SHEETS.items() if key != "rules"}

    def require(row: Row, *keys: str) -> bool:
        ok = True
        for key in keys:
            if not row.text(key):
                errors.append(f"{row.where}: thiếu '{key}'")
                ok = False
        return ok

    def require_page(row: Row, key: str) -> None:
        if not PAGE_RE.search(row.text(key)):
            errors.append(f"{row.where}: '{key}' phải có số trang (dạng 'tr. 123')")

    def severity(row: Row) -> int | None:
        value = _number(row.values.get("severity_level"))
        if value is None or value != value.to_integral_value() or not 1 <= value <= 4:
            errors.append(f"{row.where}: severity_level phải là số nguyên 1–4")
            return None
        return int(value)

    def enum(row: Row, key: str, allowed: set[str]) -> str:
        value = row.text(key)
        if value not in allowed:
            errors.append(f"{row.where}: {key}='{value}' không thuộc {sorted(allowed)}")
        return value

    # ---- nhóm bệnh
    groups: dict[str, Row] = {}
    for row in sheet["groups"]:
        if require(row, "code", "name"):
            if row.text("code") in groups:
                errors.append(f"{row.where}: trùng mã nhóm '{row.text('code')}'")
            groups[row.text("code")] = row

    # ---- hoạt chất
    ingredients: dict[str, Row] = {}
    for row in sheet["ingredients"]:
        if not require(row, "standard_name", "role"):
            continue
        name = row.text("standard_name")
        if name in ingredients:
            errors.append(f"{row.where}: trùng tên chuẩn '{name}'")
        enum(row, "role", ROLES)
        require_page(row, "Vị trí trong nguồn")
        ingredients[name] = row

    def known_ingredient(row: Row, key: str) -> str | None:
        name = row.text(key)
        if name not in ingredients:
            errors.append(f"{row.where}: hoạt chất '{name}' không có ở {SHEETS['ingredients']}")
            return None
        return name

    aliases: set[tuple[str, str]] = set()
    for row in sheet["aliases"]:
        if require(row, "active_ingredient_id", "alias_text") and known_ingredient(
            row, "active_ingredient_id"
        ):
            key = (row.text("active_ingredient_id"), row.text("alias_text"))
            if key in aliases:
                errors.append(f"{row.where}: trùng alias '{key[1]}'")
            aliases.add(key)
            require_page(row, "Vị trí trong nguồn")

    ingredient_groups: set[tuple[str, str]] = set()
    for row in sheet["ingredient_groups"]:
        if not require(row, "active_ingredient_id", "disease_group_id"):
            continue
        if known_ingredient(row, "active_ingredient_id") is None:
            continue
        if row.text("disease_group_id") not in groups:
            errors.append(f"{row.where}: mã nhóm bệnh '{row.text('disease_group_id')}' không có")
            continue
        ingredient_groups.add((row.text("active_ingredient_id"), row.text("disease_group_id")))

    classes: dict[str, Row] = {}
    for row in sheet["classes"]:
        if require(row, "class_name"):
            classes[row.text("class_name")] = row
    ingredient_classes: set[tuple[str, str]] = set()
    for row in sheet["ingredient_classes"]:
        if not require(row, "active_ingredient_id", "drug_class_id"):
            continue
        if known_ingredient(row, "active_ingredient_id") and row.text("drug_class_id") in classes:
            ingredient_classes.add((row.text("active_ingredient_id"), row.text("drug_class_id")))
        elif row.text("drug_class_id") not in classes:
            errors.append(f"{row.where}: nhóm thuốc '{row.text('drug_class_id')}' không có")

    # ---- tương tác thuốc–thuốc
    drug_rules: list[Row] = []
    drug_codes: dict[str, Row] = {}
    pairs: dict[tuple, str] = {}
    for row in sheet["drug"]:
        code = row.text("Mã tạm")
        if code:
            if code in drug_codes:
                errors.append(f"{row.where}: trùng mã tạm '{code}' với {drug_codes[code].where}")
            drug_codes[code] = row
        if not require(
            row,
            "ingredient_a_id",
            "ingredient_b_in_table_a",
            "interaction_type",
            "severity_level",
            "handling_type",
            "description",
            "source",
            "verification_status",
        ):
            continue
        a = known_ingredient(row, "ingredient_a_id")
        in_table = enum(row, "ingredient_b_in_table_a", YES_NO)
        b = row.text("ingredient_b_id")
        if in_table == "co":
            if known_ingredient(row, "ingredient_b_id") is None:
                continue
            if a == b:
                errors.append(f"{row.where}: hoạt chất A trùng B")
            key = tuple(sorted((a or "", b)))
        else:
            if b:
                errors.append(f"{row.where}: B ngoài danh mục nhưng lại chọn Hoạt chất B")
            if not row.text("ingredient_b_external_name"):
                errors.append(f"{row.where}: thiếu 'ingredient_b_external_name'")
            key = (a or "", "ext:" + row.text("ingredient_b_external_name").lower())
        if key in pairs:
            errors.append(f"{row.where}: trùng cặp với {pairs[key]}")
        pairs[key] = row.where
        enum(row, "interaction_type", INTERACTION_TYPES)
        enum(row, "handling_type", HANDLING_TYPES)
        severity(row)
        interval = row.values.get("min_interval_hours")
        if interval is not None and ((_number(interval) or 0) <= 0):
            errors.append(f"{row.where}: min_interval_hours phải là số > 0")
        if row.text("verification_status") == VERIFIED:
            require_page(row, "source")
        drug_rules.append(row)

    # ---- ngưỡng liều (AC16). Ngưỡng thuộc nội dung quy tắc cha, duyệt cùng quy tắc cha.
    thresholds: list[Row] = []
    ranges: dict[tuple, list[tuple]] = defaultdict(list)
    for row in sheet["thresholds"]:
        if not require(
            row, "interaction_id", "ingredient_ref", "dose_unit", "severity_level", "warning_text"
        ):
            continue
        code = row.text("interaction_id")
        if code not in drug_codes:
            errors.append(f"{row.where}: mã tạm tương tác '{code}' không có ở {SHEETS['drug']}")
            continue
        if drug_codes[code].text("interaction_type") != "phu_thuoc_lieu":
            errors.append(
                f"{row.where}: quy tắc '{code}' có ngưỡng liều nhưng interaction_type không phải "
                "phu_thuoc_lieu"
            )
        enum(row, "ingredient_ref", {"A", "B"})
        if row.text("dose_unit") not in dose_units:
            errors.append(
                f"{row.where}: dose_unit '{row.text('dose_unit')}' không thuộc "
                f"{SHEETS['rules']} mục 3 {sorted(dose_units)}"
            )
        severity(row)
        require_page(row, "Vị trí trong nguồn")
        bounds = []
        for key in ("min_dose", "max_dose"):
            raw = row.values.get(key)
            value = None if raw is None else _number(raw)
            if raw is not None and (value is None or value < 0):
                errors.append(f"{row.where}: {key} phải là số ≥ 0")
            bounds.append(value)
        lo, hi = bounds
        if lo is None and hi is None:
            errors.append(f"{row.where}: phải có ít nhất một trong min_dose/max_dose")
            continue
        if lo is not None and hi is not None and lo > hi:
            errors.append(f"{row.where}: min_dose lớn hơn max_dose")
            continue
        ranges[(code, row.text("ingredient_ref"), row.text("dose_unit"))].append((lo, hi, row))
        thresholds.append(row)
    for key, items in ranges.items():
        ordered = sorted(items, key=lambda t: (t[0] is not None, t[0] or 0))
        for (_lo1, hi1, r1), (lo2, _hi2, r2) in zip(ordered, ordered[1:], strict=False):
            if hi1 is None or lo2 is None or lo2 <= hi1:
                errors.append(
                    f"{r2.where}: khoảng liều chồng với {r1.where} (cùng quy tắc {key[0]})"
                )

    # ---- tương tác thức ăn
    food_rules: list[Row] = []
    foods: dict[tuple[str, str], str] = {}
    for row in sheet["food"]:
        if not require(
            row,
            "active_ingredient_id",
            "food_to_avoid",
            "severity_level",
            "reason",
            "source",
            "verification_status",
        ):
            continue
        if known_ingredient(row, "active_ingredient_id") is None:
            continue
        key = (row.text("active_ingredient_id"), row.text("food_to_avoid").lower())
        if key in foods:
            errors.append(f"{row.where}: trùng thực phẩm với {foods[key]}")
        foods[key] = row.where
        severity(row)
        if row.text("verification_status") == VERIFIED:
            require_page(row, "source")
        food_rules.append(row)

    # ---- độ phủ rà soát (G11)
    coverage: dict[str, Row] = {}
    for row in sheet["coverage"]:
        if not require(
            row,
            "active_ingredient_id",
            "Đã rà thuốc–thuốc",
            "Đã rà thức ăn",
            "Kết quả thức ăn",
            "Trang đã đọc",
            "Trạng thái xác minh",
        ):
            continue
        name = known_ingredient(row, "active_ingredient_id")
        if name is None:
            continue
        if name in coverage:
            errors.append(f"{row.where}: hoạt chất '{name}' có hơn một dòng độ phủ")
        coverage[name] = row
        enum(row, "Đã rà thuốc–thuốc", YES_NO)
        enum(row, "Đã rà thức ăn", YES_NO)
        enum(row, "Kết quả thức ăn", FOOD_RESULTS)
        require_page(row, "Trang đã đọc")
        has_food = any(r.text("active_ingredient_id") == name for r in food_rules)
        if row.text("Kết quả thức ăn") == "khong_thay" and has_food:
            errors.append(f"{row.where}: ghi 'khong_thay' nhưng có quy tắc thức ăn")
        if row.text("Kết quả thức ăn") == "co_quy_tac" and not has_food:
            errors.append(f"{row.where}: ghi 'co_quy_tac' nhưng không có quy tắc thức ăn")
    for name in ingredients:
        if name not in coverage:
            errors.append(f"{SHEETS['coverage']}: thiếu dòng độ phủ cho '{name}' (G11)")

    # ---- thuốc mẫu
    meds: dict[str, Row] = {}
    med_names: set[str] = set()
    for row in sheet["meds"]:
        if not require(row, "Mã tạm", "name"):
            continue
        if row.text("Mã tạm") in meds:
            errors.append(f"{row.where}: trùng mã tạm '{row.text('Mã tạm')}'")
        if row.text("name") in med_names:
            errors.append(f"{row.where}: trùng tên thuốc '{row.text('name')}'")
        if row.text("source") or row.text("source_ref"):
            errors.append(f"{row.where}: thuốc mẫu phải để trống source/source_ref")
        require_page(row, "Vị trí trong nguồn")
        meds[row.text("Mã tạm")] = row
        med_names.add(row.text("name"))
    med_ingredients: dict[str, list[Row]] = defaultdict(list)
    for row in sheet["med_ingredients"]:
        if not require(
            row,
            "medication_id",
            "active_ingredient_id",
            "strength_value",
            "strength_unit",
            "dosing_unit",
        ):
            continue
        if row.text("medication_id") not in meds:
            errors.append(f"{row.where}: mã tạm thuốc '{row.text('medication_id')}' không có")
            continue
        if known_ingredient(row, "active_ingredient_id") is None:
            continue
        value = _number(row.values.get("strength_value"))
        if value is None or value <= 0:
            errors.append(f"{row.where}: strength_value phải là số > 0")
        if any(
            r.text("active_ingredient_id") == row.text("active_ingredient_id")
            for r in med_ingredients[row.text("medication_id")]
        ):
            errors.append(f"{row.where}: thuốc có hoạt chất lặp lại")
        med_ingredients[row.text("medication_id")].append(row)
    for code, row in meds.items():
        if not med_ingredients.get(code):
            errors.append(
                f"{row.where}: thuốc mẫu chưa tách hoạt chất ở {SHEETS['med_ingredients']}"
            )

    # ---- đầy đủ theo hoạt chất (AC15)
    for name, row in ingredients.items():
        if not any(a == name for a, _ in aliases):
            errors.append(f"{row.where}: '{name}' chưa có alias")
        if row.text("role") == "dieu_tri_benh_nen" and not any(
            a == name for a, _ in ingredient_groups
        ):
            errors.append(f"{row.where}: '{name}' (dieu_tri_benh_nen) chưa gắn nhóm bệnh")
        if not any(
            r.text("active_ingredient_id") == name for rs in med_ingredients.values() for r in rs
        ):
            errors.append(f"{row.where}: '{name}' chưa có thuốc mẫu")

    if errors:
        return result

    # ---- lọc
    skipped: list[tuple[str, str, str]] = []
    kept_ingredients = set()
    for name in sorted(ingredients):
        cov = coverage[name]
        ok = (
            cov.text("Trạng thái xác minh") == VERIFIED
            and cov.text("Đã rà thuốc–thuốc") == "co"
            and cov.text("Đã rà thức ăn") == "co"
        )
        if ok:
            kept_ingredients.add(name)
        else:
            skipped.append((SKIP_INGREDIENT, ingredients[name].where, name))

    kept_drug = []
    for row in drug_rules:
        label = f"{row.text('Mã tạm') or row.where}"
        if row.text("ingredient_b_in_table_a") != "co":
            skipped.append((SKIP_EXTERNAL_B, row.where, label))
        elif row.text("verification_status") != VERIFIED:
            skipped.append((SKIP_NOT_VERIFIED, row.where, label))
        elif not {row.text("ingredient_a_id"), row.text("ingredient_b_id")} <= kept_ingredients:
            skipped.append((SKIP_INGREDIENT, row.where, label))
        else:
            kept_drug.append(row)

    kept_codes = {r.text("Mã tạm") for r in kept_drug}
    kept_thresholds = []
    for row in thresholds:
        code = row.text("interaction_id")
        if code in kept_codes:
            kept_thresholds.append(row)
        else:
            label = f"{code} {row.text('ingredient_ref')} {row.text('dose_unit')}"
            skipped.append((SKIP_PARENT, row.where, label))

    kept_food = []
    for row in food_rules:
        label = f"{row.text('active_ingredient_id')} – {row.text('food_to_avoid')}"
        if row.text("verification_status") != VERIFIED:
            skipped.append((SKIP_NOT_VERIFIED, row.where, label))
        elif row.text("active_ingredient_id") not in kept_ingredients:
            skipped.append((SKIP_INGREDIENT, row.where, label))
        else:
            kept_food.append(row)

    kept_meds = []
    for code in sorted(meds, key=lambda c: meds[c].text("name")):
        names = {r.text("active_ingredient_id") for r in med_ingredients[code]}
        if names <= kept_ingredients:
            kept_meds.append(code)
        else:
            skipped.append((SKIP_MEDICATION, meds[code].where, meds[code].text("name")))

    linked_classes = {c for i, c in ingredient_classes if i in kept_ingredients}
    for name in sorted(classes):
        if name not in linked_classes:
            skipped.append((SKIP_UNLINKED_CLASS, classes[name].where, name))

    # ---- dữ liệu sẽ ghi
    t_groups = sorted(
        (g.text("code"), g.text("name"), g.values.get("is_active") is not False)
        for g in groups.values()
    )
    t_ingredients = sorted(
        (
            n,
            ingredients[n].text("role"),
            ingredients[n].text("pharmacological_group") or None,
            ingredients[n].text("atc_code") or None,
            ingredients[n].text("source") or None,
        )
        for n in kept_ingredients
    )
    t_aliases = sorted((a, t) for a, t in aliases if a in kept_ingredients)
    t_ing_groups = sorted((a, g) for a, g in ingredient_groups if a in kept_ingredients)
    t_classes = sorted((c, classes[c].text("source") or None) for c in linked_classes)
    t_ing_classes = sorted((a, c) for a, c in ingredient_classes if a in kept_ingredients)
    t_meds = [
        (
            meds[c].text("name"),
            meds[c].text("raw_active_ingredient") or None,
            meds[c].text("strength_text") or None,
            meds[c].text("dosage_form") or None,
            meds[c].text("manufacturer_name") or None,
            meds[c].text("manufacturer_country") or None,
            meds[c].text("packaging_spec") or None,
        )
        for c in kept_meds
    ]
    t_med_ings = sorted(
        (
            meds[c].text("name"),
            r.text("active_ingredient_id"),
            _number(r.values.get("strength_value")),
            r.text("strength_unit"),
            r.text("dosing_unit"),
        )
        for c in kept_meds
        for r in med_ingredients[c]
    )
    t_drug = sorted(
        (
            r.text("ingredient_a_id"),
            r.text("ingredient_b_id"),
            r.text("interaction_type"),
            int(_number(r.values.get("severity_level"))),
            r.text("handling_type"),
            _number(r.values.get("min_interval_hours")),
            r.text("description"),
            r.text("source"),
        )
        for r in kept_drug
    )
    t_food = sorted(
        (
            r.text("active_ingredient_id"),
            r.text("food_to_avoid"),
            int(_number(r.values.get("severity_level"))),
            r.text("reason"),
            r.text("source"),
        )
        for r in kept_food
    )

    def _bound(row: Row, key: str) -> Decimal | None:
        raw = row.values.get(key)
        return None if raw is None else _number(raw)

    # Khóa sắp xếp tránh so None với Decimal: khoảng mở dưới (min None) đứng trước.
    t_thresholds = sorted(
        (
            (
                drug_codes[r.text("interaction_id")].text("ingredient_a_id"),
                drug_codes[r.text("interaction_id")].text("ingredient_b_id"),
                r.text("ingredient_ref"),
                _bound(r, "min_dose"),
                _bound(r, "max_dose"),
                r.text("dose_unit"),
                int(_number(r.values.get("severity_level"))),
                r.text("warning_text"),
            )
            for r in kept_thresholds
        ),
        key=lambda t: (t[0], t[1], t[2], t[5], t[3] is not None, t[3] or 0),
    )

    counts = {
        "disease_groups": len(t_groups),
        "active_ingredients": len(t_ingredients),
        "ingredient_aliases": len(t_aliases),
        "active_ingredient_disease_groups": len(t_ing_groups),
        "drug_classes": len(t_classes),
        "active_ingredient_drug_classes": len(t_ing_classes),
        "medications": len(t_meds),
        "medication_active_ingredients": len(t_med_ings),
        "active_ingredient_interactions": len(t_drug),
        "active_ingredient_interaction_dose_thresholds": len(t_thresholds),
        "drug_food_interactions": len(t_food),
    }

    out: list[str] = [
        "-- FILE SINH TỰ ĐỘNG bởi backend/scripts/build_knowledge_seed.py — KHÔNG SỬA TAY.",
        "-- Nguồn: workbook dữ liệu dược",
        "--   (docs/Team1_DTU/03_Design/Database/DrugTime_DuLieuDuoc.xlsx)",
        f"-- workbook sha256: {digest}",
        "-- Sinh lại: python scripts/build_knowledge_seed.py <workbook> "
        "--out supabase/seeds/10_knowledge_base.sql",
        "-- Chỉ chứa quy tắc verification_status = 'da_xac_minh' (QD-37).",
        "-- Nạp bởi `supabase db reset`.",
    ]
    out += [f"-- count {table}={n}" for table, n in counts.items()]
    # Một transaction cho cả file: trigger dose_threshold_guard_insert chỉ nhận ngưỡng của version
    # quy tắc tạo trong cùng transaction; nạp lên DB khác cũng là tất cả hoặc không gì.
    out += ["", "BEGIN;"]

    def block(title: str, sql: str) -> None:
        out.append("")
        out.append(f"-- {title}")
        out.append(sql)

    if t_groups:
        block(
            "disease_groups",
            "INSERT INTO disease_groups (code, name, is_active) VALUES\n" + _values(t_groups) + ";",
        )
    if t_ingredients:
        block(
            "active_ingredients",
            "INSERT INTO active_ingredients (standard_name, role, pharmacological_group, atc_code, "
            "source)\nSELECT v.standard_name, v.role::active_ingredient_role, "
            "v.pharmacological_group, v.atc_code, v.source\nFROM (VALUES\n"
            + _values(t_ingredients)
            + "\n) AS v (standard_name, role, pharmacological_group, atc_code, source);",
        )
    if t_aliases:
        block(
            "ingredient_aliases",
            "INSERT INTO ingredient_aliases (active_ingredient_id, alias_text)\n"
            "SELECT a.id, v.alias_text\nFROM (VALUES\n"
            + _values(t_aliases)
            + "\n) AS v (ingredient, alias_text)\n"
            "JOIN active_ingredients a ON a.standard_name = v.ingredient;",
        )
    if t_ing_groups:
        block(
            "active_ingredient_disease_groups",
            "INSERT INTO active_ingredient_disease_groups "
            "(active_ingredient_id, disease_group_id)\n"
            "SELECT a.id, g.id\nFROM (VALUES\n"
            + _values(t_ing_groups)
            + "\n) AS v (ingredient, code)\n"
            "JOIN active_ingredients a ON a.standard_name = v.ingredient\n"
            "JOIN disease_groups g ON g.code = v.code;",
        )
    if t_classes:
        block(
            "drug_classes",
            "INSERT INTO drug_classes (class_name, source) VALUES\n" + _values(t_classes) + ";",
        )
    if t_ing_classes:
        block(
            "active_ingredient_drug_classes",
            "INSERT INTO active_ingredient_drug_classes (active_ingredient_id, drug_class_id)\n"
            "SELECT a.id, c.id\nFROM (VALUES\n"
            + _values(t_ing_classes)
            + "\n) AS v (ingredient, class_name)\n"
            "JOIN active_ingredients a ON a.standard_name = v.ingredient\n"
            "JOIN drug_classes c ON c.class_name = v.class_name;",
        )
    if t_meds:
        block(
            "medications (thuốc mẫu; source/source_ref NULL để đồng bộ danh mục không đụng tới)",
            "INSERT INTO medications (name, raw_active_ingredient, strength_text, dosage_form, "
            "manufacturer_name, manufacturer_country, packaging_spec) VALUES\n"
            + _values(t_meds)
            + ";",
        )
    if t_med_ings:
        block(
            "medication_active_ingredients",
            "INSERT INTO medication_active_ingredients (medication_id, active_ingredient_id, "
            "strength_value, strength_unit, dosing_unit)\n"
            "SELECT m.id, a.id, v.strength_value, v.strength_unit, v.dosing_unit\nFROM (VALUES\n"
            + _values(t_med_ings)
            + "\n) AS v (medication, ingredient, strength_value, strength_unit, dosing_unit)\n"
            "JOIN medications m ON m.name = v.medication AND m.source IS NULL\n"
            "JOIN active_ingredients a ON a.standard_name = v.ingredient;",
        )
    if t_drug:
        block(
            "active_ingredient_interactions (version 1; trigger interaction_rule_set_rule_id "
            "điền rule_id)",
            "INSERT INTO active_ingredient_interactions "
            "(version, ingredient_a_id, ingredient_b_id, "
            "ingredient_b_in_table_a, interaction_type, severity_level, handling_type, "
            "min_interval_hours, description, source, verification_status)\n"
            "SELECT 1, a.id, b.id, 'co'::yes_no, v.interaction_type::interaction_type, "
            "v.severity_level, v.handling_type::handling_type, v.min_interval_hours::numeric, "
            f"v.description, v.source, '{VERIFIED}'\nFROM (VALUES\n"
            + _values(t_drug)
            + "\n) AS v (ingredient_a, ingredient_b, interaction_type, severity_level, "
            "handling_type, min_interval_hours, description, source)\n"
            "JOIN active_ingredients a ON a.standard_name = v.ingredient_a\n"
            "JOIN active_ingredients b ON b.standard_name = v.ingredient_b;",
        )
    if t_thresholds:
        block(
            "active_ingredient_interaction_dose_thresholds (gắn version hiện hành của quy tắc cha)",
            "INSERT INTO active_ingredient_interaction_dose_thresholds (interaction_id, "
            "ingredient_ref, min_dose, max_dose, dose_unit, severity_level, warning_text)\n"
            "SELECT i.id, v.ingredient_ref, v.min_dose::numeric, v.max_dose::numeric, v.dose_unit, "
            "v.severity_level, v.warning_text\nFROM (VALUES\n"
            + _values(t_thresholds)
            + "\n) AS v (ingredient_a, ingredient_b, ingredient_ref, min_dose, max_dose, "
            "dose_unit, severity_level, warning_text)\n"
            "JOIN active_ingredients a ON a.standard_name = v.ingredient_a\n"
            "JOIN active_ingredients b ON b.standard_name = v.ingredient_b\n"
            "JOIN active_ingredient_interactions i ON i.ingredient_a_id = a.id "
            "AND i.ingredient_b_id = b.id\n"
            "    AND i.superseded_at IS NULL AND i.deleted_at IS NULL;",
        )
    if t_food:
        block(
            "drug_food_interactions (version 1)",
            "INSERT INTO drug_food_interactions (version, active_ingredient_id, food_to_avoid, "
            "severity_level, reason, source, verification_status)\n"
            f"SELECT 1, a.id, v.food_to_avoid, v.severity_level, v.reason, v.source, '{VERIFIED}'\n"
            "FROM (VALUES\n"
            + _values(t_food)
            + "\n) AS v (ingredient, food_to_avoid, severity_level, reason, source)\n"
            "JOIN active_ingredients a ON a.standard_name = v.ingredient;",
        )
    out += ["", "COMMIT;"]
    result.sql = "\n".join(out) + "\n"

    lines = [f"workbook sha256: {digest}", "", "Số dòng sẽ seed:"]
    lines += [f"  {table}: {n}" for table, n in counts.items()]
    lines += ["", f"Bỏ qua ({len(skipped)}):"]
    lines += [f"  [{reason}] {where}: {label}" for reason, where, label in sorted(skipped)]
    result.report = "\n".join(lines) + "\n"
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("workbook", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):  # console Windows mặc định cp1252, mất dấu tiếng Việt
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")

    result = build(args.workbook)
    if result.errors:
        sys.stderr.write(f"{len(result.errors)} lỗi, không ghi file:\n")
        for error in result.errors:
            sys.stderr.write(f"  - {error}\n")
        return 1
    args.out.write_text(result.sql, encoding="utf-8", newline="\n")
    if args.report:
        args.report.write_text(result.report, encoding="utf-8", newline="\n")
    sys.stdout.write(result.report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
