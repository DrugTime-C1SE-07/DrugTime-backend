"""Đọc trạng thái và nội dung ảnh minh họa món (task 5.11, AC7, AC8).

Ảnh dùng chung theo món, không gắn với người dùng và không chứa dữ liệu sức khỏe, nên không qua
PEP và không ghi access_logs (contract 5.11 mục 3.2, 3.3). Chỉ cần phiên đăng nhập hợp lệ.
"""

from dataclasses import dataclass

from drugtime.modules.ai_meal.application.ports import ImageState, ImageStorage, MealImageStore
from drugtime.modules.ai_meal.domain.errors import MealImageNotFound
from drugtime.shared.uow import UnitOfWork


@dataclass(frozen=True)
class ImageContent:
    content: bytes
    content_type: str


def list_image_states(
    uow: UnitOfWork, store: MealImageStore, ids: list[int]
) -> list[ImageState]:
    """Theo thứ tự `ids`; id không tồn tại bị bỏ qua."""
    states = store.states(uow, ids)
    return [states[i] for i in ids if i in states]


def read_image_meta(uow: UnitOfWork, store: MealImageStore, image_id: int) -> ImageState:
    state = store.states(uow, [image_id]).get(image_id)
    if state is None or state.status != "ready" or not state.storage_path:
        raise MealImageNotFound()
    return state


def read_image(storage: ImageStorage, state: ImageState) -> ImageContent:
    """Gọi ngoài transaction DB. Raise `StorageUnavailable`."""
    return ImageContent(storage.download(state.storage_path), state.content_type or "image/jpeg")
