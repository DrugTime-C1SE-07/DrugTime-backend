"""Port của ai_meal (task 4.26; ảnh và gợi ý lại: task 5.11)."""

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


class MealCache(Protocol):
    """Cache raw output LLM theo key không định danh (CD10, task 5.09).

    Fail-open: không bao giờ raise; lỗi kết nối/timeout/từ chối lệnh → `get` trả None, `put` bỏ qua.
    """

    def get(self, key: str) -> str | None: ...

    def put(self, key: str, raw: str) -> None: ...


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
    def insert(
        self,
        uow: UnitOfWork,
        user_id: UUID,
        content: dict,
        previous_suggestion_id: int | None = None,
        served_from_cache: bool = False,
    ) -> tuple[int, datetime]: ...

    def find_previous(self, uow: UnitOfWork, suggestion_id: int, user_id: UUID) -> dict | None:
        """`suggestion_content` của bản ghi thuộc đúng `user_id`; None nếu không có."""
        ...

    def count_refreshes(
        self, uow: UnitOfWork, user_id: UUID, since: datetime, *, lock: bool
    ) -> int:
        """Số lần gợi ý lại thành công từ `since`. `lock`: giữ khóa theo user tới hết
        transaction để request đồng thời không vượt giới hạn (AC27)."""
        ...


@dataclass(frozen=True)
class ImageReservation:
    image_id: int
    status: str  # pending | ready | failed
    enqueue: bool


@dataclass(frozen=True)
class ImageState:
    """Trạng thái hiệu lực (pending quá 2 phút → failed) và thông tin ghi nguồn khi ready."""

    image_id: int
    status: str
    storage_path: str | None = None
    content_type: str | None = None
    photographer_name: str | None = None
    photographer_url: str | None = None
    source_url: str | None = None


class MealImageStore(Protocol):
    def reserve(self, uow: UnitOfWork, dish_key: str, query: str) -> ImageReservation: ...

    def states(self, uow: UnitOfWork, ids: list[int]) -> dict[int, ImageState]: ...


@dataclass(frozen=True)
class PendingImage:
    image_id: int
    query: str


@dataclass(frozen=True)
class FoundImage:
    content: bytes
    content_type: str
    provider_photo_id: str
    photographer_name: str
    photographer_url: str
    source_url: str


class ImageSearch(Protocol):
    def find(self, query: str) -> FoundImage:
        """Raise `ImageSearchFailed`. Chỉ `query` được gửi ra nhà cung cấp."""
        ...


class ImageStorage(Protocol):
    def upload(self, path: str, content: bytes, content_type: str) -> None: ...

    def download(self, path: str) -> bytes: ...


class ImageJobQueue(Protocol):
    def enqueue(self, image_id: int) -> None: ...
