"""Schema HTTP gợi ý bữa ăn (task 4.26; 5.11: gợi ý lại, ảnh món), khớp api_contract/openapi.json.

Field lạ bị từ chối (`extra="forbid"`). Khai báo dị ứng / hạn chế chỉ có hai dạng hợp lệ (QD-40).
"""

from datetime import datetime
from typing import Annotated, Literal
from zoneinfo import ZoneInfo

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

_VIETNAM = ZoneInfo("Asia/Ho_Chi_Minh")


def _text(max_length: int):
    return Annotated[str, StringConstraints(min_length=1, max_length=max_length, pattern=r"\S")]


MealTypeValue = Literal["sang", "trua", "toi"]
DishTypeValue = Literal[
    "com", "mon_nuoc", "mon_man", "mon_xao", "mon_hap_luoc", "chao_sup", "salad", "khac"
]


class ErrorDetail(BaseModel):
    detail: str


class _Declaration(BaseModel):
    model_config = ConfigDict(extra="forbid")

    none: bool
    items: list[_text(40)]

    @model_validator(mode="after")
    def _two_valid_shapes(self):
        if self.none and self.items:
            raise ValueError("items must be empty when none is true")
        if not self.none and not self.items:
            raise ValueError("items must not be empty when none is false")
        if len({i.strip().casefold() for i in self.items}) != len(self.items):
            raise ValueError("items must be unique")
        return self


class DietaryDeclaration(_Declaration):
    items: list[_text(40)] = Field(max_length=10)


class AllergyDeclaration(_Declaration):
    """Every allergy of the health profile: 15 catalog entries + 30 custom names (QD-40)."""

    items: list[_text(40)] = Field(max_length=45)


class MealSuggestionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    meal_type: MealTypeValue
    allergies: AllergyDeclaration
    dietary_restrictions: DietaryDeclaration
    preferences: list[_text(40)] = Field(default_factory=list, max_length=5)
    # Tùy chọn; gửi `null` tường minh bị từ chối như contract (kiểu không nhận None).
    previous_suggestion_id: Annotated[int, Field(ge=1, strict=True)] = None  # type: ignore[assignment]

    @field_validator("preferences")
    @classmethod
    def _unique(cls, value: list[str]) -> list[str]:
        if len({v.strip().casefold() for v in value}) != len(value):
            raise ValueError("preferences must be unique")
        return value


class MealBenefitTarget(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["condition", "allergy", "restriction", "general"]
    label: str | None


class MealBenefit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str
    related_to: MealBenefitTarget


class MealIngredient(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    amount: str
    group: Literal["chinh", "gia_vi"]
    use_sparingly: bool


class MealImageAttribution(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: Literal["pixabay"]
    photographer_name: str
    photographer_url: str
    source_url: str


class MealImage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    image_id: int
    status: Literal["pending", "ready", "failed"]
    url: str | None
    attribution: MealImageAttribution | None


class MealImageStatusList(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[MealImage]


class MealSuggestion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    dish_type: DishTypeValue
    is_new: bool
    tags: list[str]
    kcal_estimate: int
    cook_minutes: int
    image: MealImage | None
    benefits: list[MealBenefit]
    ingredients: list[MealIngredient]


class MealIngredientRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int
    standard_name: str


class MealFoodWarning(BaseModel):
    """Cùng hình dạng `FoodInteractionWarning` của contract (4.05)."""

    model_config = ConfigDict(extra="forbid")

    rule_id: int
    version_id: int
    ingredient: MealIngredientRef
    food_to_avoid: str
    severity_level: int
    reason: str
    source: str


class MealFoodCheck(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["co_tuong_tac", "da_kiem_tra_khong_thay", "khong_du_du_lieu"]
    warnings: list[MealFoodWarning]


class MealSuggestionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    suggestion_id: int
    meal_type: MealTypeValue
    suggestions: list[MealSuggestion]
    food_check: MealFoodCheck
    disclaimer: str
    refreshes_remaining: int = Field(ge=0)
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def _vietnam_offset(cls, value: datetime) -> datetime:
        return value.astimezone(_VIETNAM)
