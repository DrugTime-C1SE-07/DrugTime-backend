"""Use case Worker: tìm, tải, kiểm và lưu ảnh minh họa một món (task 5.11, AC7, AC8).

Mọi lỗi kho ảnh hoặc kho lưu trữ → `failed`; gợi ý không bị ảnh hưởng. Không retry trong task:
ảnh `failed` được thử lại khi có gợi ý mới sau 24 giờ (hàm `ai_meal_reserve_image`).
Log chỉ ghi id ảnh và mã lý do; không ghi query, URL hay key.
"""

import logging
from collections.abc import Callable
from contextlib import AbstractContextManager
from typing import Protocol

from drugtime.modules.ai_meal.application.ports import (
    FoundImage,
    ImageSearch,
    ImageStorage,
    PendingImage,
)
from drugtime.modules.ai_meal.domain.errors import ImageSearchFailed, StorageUnavailable
from drugtime.shared.uow import UnitOfWork

_log = logging.getLogger(__name__)

_EXTENSIONS = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}


class ImageRecords(Protocol):
    def load_pending(self, uow: UnitOfWork, image_id: int) -> PendingImage | None: ...

    def mark_ready(
        self, uow: UnitOfWork, image_id: int, storage_path: str, found: FoundImage
    ) -> None: ...

    def mark_failed(self, uow: UnitOfWork, image_id: int) -> None: ...


def storage_path(image_id: int, content_type: str) -> str:
    return f"{image_id}.{_EXTENSIONS[content_type]}"


def fetch_image(
    image_id: int,
    *,
    uow_factory: Callable[[], AbstractContextManager[UnitOfWork]],
    records: ImageRecords,
    search: ImageSearch,
    storage: ImageStorage,
) -> str:
    """Trả kết quả: `skipped` | `ready` | `failed:<lý do>`.

    Đọc dòng `pending` trong transaction ngắn, gọi mạng ngoài transaction, rồi ghi kết quả.
    """
    with uow_factory() as uow:
        pending = records.load_pending(uow, image_id)
    if pending is None:
        return "skipped"  # đã ready/failed, hoặc Worker khác đang xử lý

    try:
        found = search.find(pending.query)
        path = storage_path(image_id, found.content_type)
        storage.upload(path, found.content, found.content_type)
    except (ImageSearchFailed, StorageUnavailable) as exc:
        reason = exc.reason
        _log.warning("ai_meal image_failed id=%s reason=%s", image_id, reason)
        with uow_factory() as uow:
            records.mark_failed(uow, image_id)
        return f"failed:{reason}"

    with uow_factory() as uow:
        records.mark_ready(uow, image_id, path, found)
    _log.info("ai_meal image_ready id=%s", image_id)
    return "ready"
