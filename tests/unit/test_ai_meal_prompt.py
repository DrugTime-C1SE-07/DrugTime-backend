"""Input, prompt builder, khớp chuỗi của gợi ý bữa ăn (4.26: AC1, AC2, AC4; 5.11: AC14, AC20)."""

import json
from uuid import uuid4

import pytest

from drugtime.modules.ai_meal.domain.errors import MealInputIncomplete
from drugtime.modules.ai_meal.domain.model import DietaryDeclaration, MealSuggestionInput
from drugtime.modules.ai_meal.domain.prompt import (
    LLM_OUTPUT_SCHEMA,
    PROMPT_VERSION,
    build_prompt,
)
from drugtime.modules.ai_meal.domain.text_match import contains_any, keywords, normalize

NONE = DietaryDeclaration(True, ())


def _input(order=1, **overrides):
    lists = {
        "active_ingredients": ["Losartan", "Metformin"],
        "conditions": ["Tăng huyết áp", "Đái tháo đường"],
        "avoid_foods": ["Chuối", "Rượu và đồ uống có cồn"],
        "allergies": DietaryDeclaration(False, ("Tôm", "Hải sản")),
        "restrictions": DietaryDeclaration(False, ("Ít đường",)),
        "preferences": ["Ít cay", "Món nước"],
    }
    if order < 0:
        lists = {
            k: (DietaryDeclaration(v.none, tuple(reversed(v.items)))
                if isinstance(v, DietaryDeclaration) else list(reversed(v)))
            for k, v in lists.items()
        }
    lists.update(overrides)
    return MealSuggestionInput.build(
        meal_type="trua",
        active_ingredients=lists["active_ingredients"],
        conditions=lists["conditions"],
        avoid_foods=lists["avoid_foods"],
        allergies=lists["allergies"],
        restrictions=lists["restrictions"],
        preferences=lists["preferences"],
    )


def test_prompt_deterministic_under_reordering__AC1():
    a, b = build_prompt(_input(1)), build_prompt(_input(-1))
    assert a.system == b.system and a.user == b.user and a.targets == b.targets


def test_input_trimmed_and_deduplicated__AC1():
    data = _input(avoid_foods=["  Chuối ", "chuối", "CHUỐI", "Cam"])
    assert data.avoid_foods == ("Cam", "CHUỐI")  # một bản cho mỗi khóa chuẩn hóa, sắp xếp


def test_prompt_lists_all_avoid_and_allergies__AC1():
    p = build_prompt(_input())
    assert PROMPT_VERSION in p.user and p.version == PROMPT_VERSION
    context = json.loads(p.user.split("<ngu_canh>\n")[1].split("\n</ngu_canh>")[0])
    assert context["meal_type"] == "trua"
    assert context["thuc_pham_can_tranh"] == ["Chuối", "Rượu và đồ uống có cồn"]
    assert [x["ten"] for x in context["di_ung"]] == ["Hải sản", "Tôm"]
    assert [x["khoa"] for x in context["di_ung"]] == ["allergy:1", "allergy:2"]
    assert [x["ten"] for x in context["benh_nen"]] == ["Đái tháo đường", "Tăng huyết áp"]
    assert context["han_che_an_uong"] == [{"khoa": "restriction:1", "ten": "Ít đường"}]
    assert "Không nhắc tên thuốc" in p.system
    assert "JSON" in p.user
    assert p.targets["condition:2"].label == "Tăng huyết áp"
    assert p.targets["general"].type == "general" and p.targets["general"].label is None


@pytest.mark.parametrize("meal_type", ["", "khuya", "SANG", None])
def test_invalid_meal_type_rejected__AC1(meal_type):
    with pytest.raises(MealInputIncomplete):
        MealSuggestionInput.build(
            meal_type=meal_type, active_ingredients=(), conditions=(), avoid_foods=(),
            allergies=NONE, restrictions=NONE,
        )


@pytest.mark.parametrize(
    "field,value",
    [
        ("allergies", None),
        ("restrictions", None),
        ("allergies", DietaryDeclaration(False, ())),
        ("allergies", DietaryDeclaration(False, ("  ",))),
        ("restrictions", DietaryDeclaration(True, ("Chay",))),
    ],
)
def test_incomplete_declarations_rejected__AC4(field, value):
    with pytest.raises(MealInputIncomplete):
        _input(**{field: value})


def test_none_declarations_accepted__AC4():
    data = _input(allergies=NONE, restrictions=NONE)
    assert data.allergies == () and data.restrictions == ()


def test_payload_has_no_identifiers__AC2():
    patient_id, name, email = uuid4(), "Nguyễn Văn Bệnh", "benh@example.com"
    # Input không có trường định danh: kể cả khi người gọi biết các giá trị này.
    p = build_prompt(_input(), drug_names=["Cozaar 50mg"])
    payload = p.system + p.user + json.dumps(LLM_OUTPUT_SCHEMA)
    for secret in (str(patient_id), name, email, "Cozaar"):
        assert secret not in payload
    assert set(MealSuggestionInput.__dataclass_fields__) == {
        "meal_type", "active_ingredients", "conditions", "avoid_foods",
        "allergies", "restrictions", "preferences",
    }
    assert "cozaar 50mg" in p.drug_keywords  # chỉ dùng để lọc phía backend


SUPPORTED = {"type", "properties", "required", "additionalProperties", "items", "enum"}


def _keys(node):
    if isinstance(node, dict):
        for k, v in node.items():
            if k != "properties":
                yield k
                yield from _keys(v)
            else:
                for child in v.values():
                    yield from _keys(child)
    elif isinstance(node, list):
        for v in node:
            yield from _keys(v)


def _objects(node):
    if isinstance(node, dict):
        if node.get("type") == "object":
            yield node
        for v in node.values():
            yield from _objects(v)


def test_output_schema_uses_supported_keywords_only():
    assert set(_keys(LLM_OUTPUT_SCHEMA)) <= SUPPORTED
    for obj in _objects(LLM_OUTPUT_SCHEMA):
        assert obj["additionalProperties"] is False
        assert set(obj["required"]) == set(obj["properties"])
    assert "eating_tips" not in json.dumps(LLM_OUTPUT_SCHEMA)


@pytest.mark.parametrize(
    "raw,expected",
    [("Tôm", "tom"), ("  Đậu   PHỤ ", "dau phu"), ("Cá rô đồng", "ca ro dong")],
)
def test_normalize_strips_vietnamese_diacritics(raw, expected):
    assert normalize(raw) == expected


def test_keywords_split_free_text_avoid_food():
    keys = keywords(["Thực phẩm giàu kali (chuối, cam) và muối thay thế chứa kali"])
    assert {"chuoi", "cam", "muoi thay the chua kali"} <= set(keys)


def test_contains_any_respects_word_boundaries():
    assert contains_any("Chuối tiêu", ["chuoi"])
    assert contains_any("Canh Tôm chua", ["tom"])
    assert not contains_any("Gạo lứt", ["ga"])


# --- Task 5.11: meal-v2 ----------------------------------------------------------------------


def test_meal_v2_version_and_schema__AC20():
    assert PROMPT_VERSION == "meal-v2"
    item = LLM_OUTPUT_SCHEMA["properties"]["suggestions"]["items"]
    assert item["properties"]["dish_type"]["enum"] == [
        "com", "mon_nuoc", "mon_man", "mon_xao", "mon_hap_luoc", "chao_sup", "salad", "khac"
    ]
    assert item["properties"]["image_query"] == {"type": "string"}
    assert {"dish_type", "image_query"} <= set(item["required"])


@pytest.mark.parametrize(
    "phrase",
    [
        "MỘT NGƯỜI, MỘT BỮA",  # khẩu phần
        "ít nhất 2 loại khác nhau",  # đa dạng
        "nguồn tinh bột",  # trưa/tối có tinh bột
        "phù hợp với từng bệnh nền",
        "use_sparingly = true",
        "chỉ số đường huyết cao",
        "không lặp nguyên câu",
        "tối đa 60 ký tự",  # image_query
        "Chỉ mô tả món ăn",
    ],
)
def test_meal_v2_quality_rules_in_system_prompt__AC20(phrase):
    assert phrase in build_prompt(_input()).system


def _context(p):
    return json.loads(p.user.split("<ngu_canh>" + chr(10))[1].split(chr(10) + "</ngu_canh>")[0])


def test_first_request_has_no_previous_dishes__AC14():
    p = build_prompt(_input())
    assert "mon_da_goi_y" not in _context(p)
    assert "món mới" not in p.user.split("</ngu_canh>")[1]


def test_refresh_prompt_lists_old_names_and_count__AC14():
    names = ["Canh chua cá", " canh chua cá ", "Cơm gà"]
    p = build_prompt(_input(), avoid_dish_names=names, count=3)
    ctx = _context(p)
    assert ctx["mon_da_goi_y"] == ["Canh chua cá", "Cơm gà"]
    assert "đúng 3 món mới" in p.user
    # Chỉ tên món: không định danh, không thêm khóa nào khác ngoài ngữ cảnh 4.26.
    assert set(ctx) == {
        "phien_ban_prompt", "meal_type", "bua_an", "benh_nen", "di_ung", "han_che_an_uong",
        "thuc_pham_can_tranh", "hoat_chat_dang_dung", "so_thich", "mon_da_goi_y",
    }
