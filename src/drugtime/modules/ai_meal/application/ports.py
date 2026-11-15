"""Port của ai_meal (task 4.26)."""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from drugtime.modules.ai_meal.domain.model import MealPrompt
from drugtime.shared.uow import UnitOfWork


class MealSuggester(Protocol):
    """LLM provider. Nhận prompt đã tối thiểu hóa (không định danh), trả văn bản JSON thô.

    Raise `LlmUnavailable` / `LlmInvalidOutput`; không retry (ngân sách 10 giây của PB37).
    """

    def suggest(self, prompt: MealPrompt) -> str: ...


@dataclass(frozen=True)
class FoodWarningView:
    rule_id: int
    version_id: int
    ingredient_id: int
    ingredient_name: str
    food_to_avoid: str
    severity_level: int
    reason: str
    source: str


@dataclass(frozen=True)
class FoodCheck:
    """Kết quả engine thuốc–thực phẩm tất định (4.05) cho mọi thuốc đang dùng."""

    status: str  # co_tuong_tac | da_kiem_tra_khong_thay | khong_du_du_lieu
    warnings: tuple[FoodWarningView, ...]  # đã sắp và khử trùng
    ingredient_names: tuple[str, ...]
    medication_names: tuple[str, ...]  # chỉ để lọc output, không gửi provider


class FoodCheckReader(Protocol):
    def read(self, uow: UnitOfWork, patient_id: UUID) -> FoodCheck:
        """Người gọi đã kiểm quyền qua PEP."""
        ...


class ConditionReader(Protocol):
    def names(self, uow: UnitOfWork, patient_id: UUID) -> list[str]:
        """Tên bệnh nền trong hồ sơ. Người gọi đã kiểm quyền qua PEP."""
        ...


class MealSuggestionStore(Protocol):
    def insert(self, uow: UnitOfWork, user_id: UUID, content: dict) -> tuple[int, datetime]: ...
