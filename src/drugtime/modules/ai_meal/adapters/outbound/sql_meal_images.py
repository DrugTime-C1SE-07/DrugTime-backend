"""Metadata ảnh món `meal_images` (task 5.11).

API (api_role): chỉ SELECT và gọi hàm `ai_meal_reserve_image` (SECURITY DEFINER).
Worker (worker_role): SELECT và UPDATE kết quả.
Trạng thái hiệu lực: `pending` quá 2 phút được đọc là `failed`.
"""

from sqlalchemy import bindparam, text

from drugtime.modules.ai_meal.application.ports import (
    FoundImage,
    ImageReservation,
    ImageState,
    PendingImage,
)
from drugtime.shared.uow import UnitOfWork

_EFFECTIVE_STATUS = (
    "CASE WHEN status = 'pending' AND updated_at < now() - interval '2 minutes' "
    "THEN 'failed' ELSE status END"
)
_STATE_COLUMNS = (
    f"id, {_EFFECTIVE_STATUS} AS status, storage_path, content_type, photographer_name, "
    "photographer_url, source_url"
)


def _state(row) -> ImageState:
    ready = row.status == "ready"
    return ImageState(
        image_id=row.id,
        status=row.status,
        storage_path=row.storage_path if ready else None,
        content_type=row.content_type if ready else None,
        photographer_name=row.photographer_name if ready else None,
        photographer_url=row.photographer_url if ready else None,
        source_url=row.source_url if ready else None,
    )


class SqlMealImages:
    def reserve(self, uow: UnitOfWork, dish_key: str, query: str) -> ImageReservation:
        row = uow.connection.execute(
            text("SELECT image_id, status, enqueue FROM ai_meal_reserve_image(:k, :q)"),
            {"k": dish_key, "q": query},
        ).one()
        return ImageReservation(row.image_id, row.status, row.enqueue)

    def states(self, uow: UnitOfWork, ids: list[int]) -> dict[int, ImageState]:
        if not ids:
            return {}
        rows = uow.connection.execute(
            text(f"SELECT {_STATE_COLUMNS} FROM meal_images WHERE id IN :ids").bindparams(
                bindparam("ids", expanding=True)
            ),
            {"ids": list(ids)},
        ).all()
        return {row.id: _state(row) for row in rows}

    # --- Worker -------------------------------------------------------------------------

    def load_pending(self, uow: UnitOfWork, image_id: int) -> PendingImage | None:
        row = uow.connection.execute(
            text(
                "SELECT id, image_query FROM meal_images "
                "WHERE id = :id AND status = 'pending' FOR UPDATE SKIP LOCKED"
            ),
            {"id": image_id},
        ).one_or_none()
        return None if row is None else PendingImage(row.id, row.image_query)

    def mark_ready(
        self, uow: UnitOfWork, image_id: int, storage_path: str, found: FoundImage
    ) -> None:
        uow.connection.execute(
            text(
                "UPDATE meal_images SET status = 'ready', storage_path = :path, "
                "content_type = :ct, size_bytes = :size, provider = 'pixabay', "
                "provider_photo_id = :pid, photographer_name = :pn, photographer_url = :pu, "
                "source_url = :su, updated_at = now() WHERE id = :id"
            ),
            {
                "id": image_id,
                "path": storage_path,
                "ct": found.content_type,
                "size": len(found.content),
                "pid": found.provider_photo_id,
                "pn": found.photographer_name,
                "pu": found.photographer_url,
                "su": found.source_url,
            },
        )

    def mark_failed(self, uow: UnitOfWork, image_id: int) -> None:
        uow.connection.execute(
            text(
                "UPDATE meal_images SET status = 'failed', updated_at = now() "
                "WHERE id = :id AND status = 'pending'"
            ),
            {"id": image_id},
        )
