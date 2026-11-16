"""Giao diện công khai của ai_meal."""

import logging
from uuid import UUID

from fastapi import APIRouter

from drugtime.modules.ai_meal.adapters.inbound.http import router as _suggestions_router
from drugtime.modules.ai_meal.adapters.inbound.images_http import router as _images_router
from drugtime.modules.ai_meal.adapters.outbound import sql_erasure
from drugtime.shared.config import Settings, get_settings
from drugtime.shared.uow import UnitOfWork

__all__ = ["eraser", "log_effective_config", "router"]

_log = logging.getLogger("drugtime.modules.ai_meal")

router = APIRouter()
router.include_router(_suggestions_router)
router.include_router(_images_router)


class _Eraser:
    name = "ai_meal"

    def erase_user(self, uow: UnitOfWork, user_id: UUID) -> None:
        sql_erasure.erase(uow, user_id)


eraser = _Eraser()


def log_effective_config(settings: Settings | None = None) -> None:
    """Một dòng cấu hình hiệu lực khi khởi động (task 5.11, AC22). Không bao giờ ghi key."""
    s = settings or get_settings()
    _log.info(
        "ai_meal config llm_enabled=%s llm_base_url=%s llm_model=%s llm_timeout=%s "
        "image_enabled=%s refresh_daily_limit=%s",
        s.ai_meal_llm_enabled,
        s.llm_api_url or "mặc định",
        s.llm_model,
        s.llm_timeout_seconds,
        s.ai_meal_image_enabled,
        s.ai_meal_refresh_daily_limit,
    )
