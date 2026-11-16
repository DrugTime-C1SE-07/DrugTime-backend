"""Gợi ý lại: chọn món cũ, lọc lại, ghép, lượt theo ngày (task 5.11: AC14, AC15, AC27)."""

from datetime import UTC, datetime

import pytest

from drugtime.modules.ai_meal.domain.model import BenefitTarget, MealSuggestion
from drugtime.modules.ai_meal.domain.refresh import (
    day_start_vn,
    merge,
    old_names,
    remaining,
    seconds_to_midnight_vn,
    select_kept,
)
from drugtime.modules.ai_meal.domain.text_match import keywords

TARGETS = {
    "general": BenefitTarget("general", None),
    "condition:1": BenefitTarget("condition", "Tăng huyết áp"),
}


def _dish(name, *, ingredient="Gà", benefits=None, **extra):
    d = {
        "name": name,
        "tags": ["Ít muối"],
        "kcal_estimate": 400,
        "cook_minutes": 20,
        "benefits": benefits
        or [
            {"text": "Ít muối", "related_to": {"type": "condition", "label": "Tăng huyết áp"}},
            {"text": "Nhiều đạm", "related_to": {"type": "general", "label": None}},
        ],
        "ingredients": [
            {"name": ingredient, "amount": "100 g", "group": "chinh", "use_sparingly": False}
        ],
        "dish_type": "mon_man",
        "image_id": 7,
        "is_new": True,
    }
    d.update(extra)
    return d


def _content(*dishes):
    return {"prompt_version": "meal-v2", "meal_type": "trua", "suggestions": list(dishes)}


def test_main_dish_dropped_and_at_most_three_kept_in_order__AC14():
    content = _content(*(_dish(f"Món {i}") for i in range(6)))
    kept = select_kept(content, (), TARGETS)
    assert [d.name for d in kept] == ["Món 1", "Món 2", "Món 3"]
    assert all(d.is_new is False and d.image_id == 7 and d.image_query is None for d in kept)
    assert kept[0].dish_type == "mon_man"


def test_kept_dishes_refiltered_with_current_avoid_and_allergies__AC15():
    content = _content(
        _dish("Món chính"),
        _dish("Canh chua cá", ingredient="Cá lóc"),
        _dish("Gà luộc"),
        _dish("Tôm rang"),
    )
    kept = select_kept(content, keywords(["cá", "Tôm"]), TARGETS)
    assert [d.name for d in kept] == ["Gà luộc"]


def test_invalid_kept_dish_replaced_by_next_valid__AC15():
    content = _content(*(_dish(n) for n in ("Chính", "Cá kho", "A", "B", "C")))
    kept = select_kept(content, keywords(["cá"]), TARGETS)
    assert [d.name for d in kept] == ["A", "B", "C"]


def test_benefit_with_removed_target_dropped__AC15():
    only_old_condition = [
        {"text": "Hợp tiểu đường", "related_to": {"type": "condition", "label": "Tiểu đường"}}
    ]
    content = _content(_dish("Chính"), _dish("Mất hết lợi ích", benefits=only_old_condition),
                       _dish("Còn lợi ích"))
    kept = select_kept(content, (), TARGETS)
    assert [d.name for d in kept] == ["Còn lợi ích"]
    assert [b.related_to for b in kept[0].benefits] == [
        BenefitTarget("condition", "Tăng huyết áp"), BenefitTarget("general", None)
    ]


def test_v1_record_without_dish_type_or_image__AC14():
    v1 = _dish("Cũ")
    del v1["dish_type"], v1["image_id"], v1["is_new"]
    kept = select_kept(_content(_dish("Chính"), v1), (), TARGETS)
    assert kept[0].dish_type == "khac" and kept[0].image_id is None


@pytest.mark.parametrize(
    "broken",
    [None, "x", {"name": 1}, _dish("x", ingredients=[{"name": "a"}]),
     _dish("y", kcal_estimate="1")],
)
def test_malformed_old_dish_skipped(broken):
    kept = select_kept(_content(_dish("Chính"), broken, _dish("Tốt")), (), TARGETS)
    assert [d.name for d in kept] == ["Tốt"]


def test_content_without_suggestions_gives_nothing():
    assert select_kept({}, (), TARGETS) == ()
    assert old_names({"suggestions": "x"}) == ()


def test_old_names_include_main_dish__AC14():
    assert old_names(_content(_dish("A"), _dish("B"))) == ("A", "B")


def _s(name, is_new):
    return MealSuggestion(name, (), 400, 20, (), (), is_new=is_new)


def test_merge_new_first_dedup_and_cap_six__AC14():
    new = [_s("Mới 1", True), _s("Mới 2", True), _s("Mới 3", True)]
    kept = [_s("mới 1", False), _s("Cũ A", False), _s("Cũ B", False), _s("Cũ C", False),
            _s("Cũ D", False)]
    merged = merge(new, kept)
    assert [d.name for d in merged] == ["Mới 1", "Mới 2", "Mới 3", "Cũ A", "Cũ B", "Cũ C"]
    assert [d.is_new for d in merged] == [True] * 3 + [False] * 3


@pytest.mark.parametrize(
    ("utc", "expected_start_utc"),
    [
        (datetime(2026, 11, 16, 16, 59, tzinfo=UTC), datetime(2026, 11, 15, 17, 0, tzinfo=UTC)),
        (datetime(2026, 11, 16, 17, 0, tzinfo=UTC), datetime(2026, 11, 16, 17, 0, tzinfo=UTC)),
        (datetime(2026, 11, 16, 17, 1, tzinfo=UTC), datetime(2026, 11, 16, 17, 0, tzinfo=UTC)),
    ],
)
def test_day_start_vn_boundaries__AC27(utc, expected_start_utc):
    """23:59 / 00:00 / 00:01 giờ Việt Nam."""
    assert day_start_vn(utc) == expected_start_utc


def test_seconds_to_midnight_vn__AC27():
    assert seconds_to_midnight_vn(datetime(2026, 11, 16, 16, 59, 0, tzinfo=UTC)) == 60
    assert seconds_to_midnight_vn(datetime(2026, 11, 16, 17, 0, 0, tzinfo=UTC)) == 86400
    assert seconds_to_midnight_vn(datetime(2026, 11, 16, 16, 59, 59, 999999, tzinfo=UTC)) == 1


@pytest.mark.parametrize(
    ("used", "is_refresh", "expected"),
    [(0, False, 2), (0, True, 1), (1, True, 0), (2, False, 0), (5, True, 0)],
)
def test_remaining_never_negative__AC27(used, is_refresh, expected):
    assert remaining(2, used, is_refresh=is_refresh) == expected
