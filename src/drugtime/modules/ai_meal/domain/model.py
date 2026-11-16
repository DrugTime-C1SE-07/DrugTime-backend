"""Mô hình gợi ý bữa ăn (task 4.26): input đã tối thiểu hóa và output đã parse.

Input không có trường định danh nào (QD-41, AC2): chỉ tên hoạt chất, tên bệnh nền, thực phẩm
cần tránh, dị ứng, hạn chế, sở thích và bữa ăn. Mọi danh sách được trim, khử trùng và sắp xếp
để cùng dữ liệu luôn cho cùng prompt (AC1) và cache key ở 5.09.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum

from drugtime.modules.ai_meal.domain.errors import MealInputIncomplete
from drugtime.modules.ai_meal.domain.text_match import normalize

MEAL_DISCLAIMER = (
    "Gợi ý do AI tạo, chỉ mang tính tham khảo, không thay thế tư vấn của bác sĩ hay "
    "chuyên gia dinh dưỡng. Hãy hỏi bác sĩ hoặc dược sĩ trước khi thay đổi chế độ ăn."
)


class MealType(StrEnum):
    SANG = "sang"
    TRUA = "trua"
    TOI = "toi"


class MealDishType(StrEnum):
    """Loại món để đa dạng hóa gợi ý (task 5.11). Không mang ý nghĩa an toàn."""

    COM = "com"
    MON_NUOC = "mon_nuoc"
    MON_MAN = "mon_man"
    MON_XAO = "mon_xao"
    MON_HAP_LUOC = "mon_hap_luoc"
    CHAO_SUP = "chao_sup"
    SALAD = "salad"
    KHAC = "khac"


def clean_list(values: Iterable[str]) -> tuple[str, ...]:
    """Trim, gộp khoảng trắng, bỏ rỗng, khử trùng (không phân biệt hoa thường/dấu), sắp xếp."""
    by_key: dict[str, str] = {}
    for value in values:
        text = " ".join(value.split())
        key = normalize(text)
        if key and (key not in by_key or text < by_key[key]):
            by_key[key] = text
    return tuple(sorted(by_key.values(), key=lambda v: (normalize(v), v)))


@dataclass(frozen=True)
class DietaryDeclaration:
    """Khai báo bắt buộc (QD-40): `none` = người dùng xác nhận không có."""

    none: bool
    items: tuple[str, ...]

    @classmethod
    def of(cls, declaration: "DietaryDeclaration | None", field: str) -> "DietaryDeclaration":
        if declaration is None:
            raise MealInputIncomplete(f"{field}_missing")
        items = clean_list(declaration.items)
        if declaration.none and items:
            raise MealInputIncomplete(f"{field}_inconsistent")
        if not declaration.none and not items:
            raise MealInputIncomplete(f"{field}_missing")
        return cls(declaration.none, items)


@dataclass(frozen=True)
class MealSuggestionInput:
    meal_type: MealType
    active_ingredients: tuple[str, ...]
    conditions: tuple[str, ...]
    avoid_foods: tuple[str, ...]
    allergies: tuple[str, ...]
    restrictions: tuple[str, ...]
    preferences: tuple[str, ...]

    @classmethod
    def build(
        cls,
        *,
        meal_type: str,
        active_ingredients: Iterable[str],
        conditions: Iterable[str],
        avoid_foods: Iterable[str],
        allergies: DietaryDeclaration | None,
        restrictions: DietaryDeclaration | None,
        preferences: Iterable[str] = (),
    ) -> "MealSuggestionInput":
        try:
            meal = MealType(meal_type)
        except ValueError:
            raise MealInputIncomplete("meal_type_invalid") from None
        return cls(
            meal_type=meal,
            active_ingredients=clean_list(active_ingredients),
            conditions=clean_list(conditions),
            avoid_foods=clean_list(avoid_foods),
            allergies=DietaryDeclaration.of(allergies, "allergies").items,
            restrictions=DietaryDeclaration.of(restrictions, "dietary_restrictions").items,
            preferences=clean_list(preferences),
        )


@dataclass(frozen=True)
class BenefitTarget:
    """Lợi ích gắn với gì: `condition`, `allergy`, `restriction` hoặc `general` (label None)."""

    type: str
    label: str | None


@dataclass(frozen=True)
class MealPrompt:
    version: str
    meal_type: MealType
    system: str
    user: str
    # Khóa `related_to` đã cấp trong prompt → đích hiển thị; không bao giờ ra tới client.
    targets: dict[str, BenefitTarget]
    # Chỉ dùng để lọc phía backend, không gửi cho provider.
    blocked_food_keywords: tuple[str, ...]
    drug_keywords: tuple[str, ...]


@dataclass(frozen=True)
class MealBenefit:
    text: str
    related_to: BenefitTarget


@dataclass(frozen=True)
class MealIngredient:
    name: str
    amount: str
    group: str
    use_sparingly: bool


@dataclass(frozen=True)
class MealSuggestion:
    name: str
    tags: tuple[str, ...]
    kcal_estimate: int
    cook_minutes: int
    benefits: tuple[MealBenefit, ...]
    ingredients: tuple[MealIngredient, ...]
    dish_type: str = MealDishType.KHAC.value
    # Cụm từ tìm ảnh tiếng Anh do LLM sinh; chỉ gửi kho ảnh, không trả client, không lưu
    # trong `meal_suggestions` (task 5.11, AC9).
    image_query: str | None = None
    # True: món tạo ở request này; False: món giữ lại khi gợi ý lại (task 5.11).
    is_new: bool = True
    image_id: int | None = None


@dataclass(frozen=True)
class MealSuggestionSet:
    prompt_version: str
    meal_type: MealType
    suggestions: tuple[MealSuggestion, ...]
