"""Schema HTTP của gợi ý bữa ăn (task 4.26), khớp api_contract/openapi.json.

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


class ErrorDetail(BaseModel):
    detail: str


class DietaryDeclaration(BaseModel):
    model_config = ConfigDict(extra="forbid")

    none: bool
    items: list[_text(40)] = Field(max_length=10)

    @model_validator(mode="after")
    def _two_valid_shapes(self) -> "DietaryDeclaration":
        if self.none and self.items:
            raise ValueError("items must be empty when none is true")
        if not self.none and not self.items:
            raise ValueError("items must not be empty when none is false")
        if len({i.strip().casefold() for i in self.items}) != len(self.items):
            raise ValueError("items must be unique")
        return self


class MealSuggestionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    meal_type: MealTypeValue
    allergies: DietaryDeclaration
    dietary_restrictions: DietaryDeclaration
    preferences: list[_text(40)] = Field(default_factory=list, max_length=5)

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


class MealSuggestion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    tags: list[str]
    kcal_estimate: int
    cook_minutes: int
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
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def _vietnam_offset(cls, value: datetime) -> datetime:
        return value.astimezone(_VIETNAM)
