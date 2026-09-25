"""Giao diện công khai của ai_meal."""

from uuid import UUID

from drugtime.modules.ai_meal.adapters.inbound.http import router
from drugtime.modules.ai_meal.adapters.outbound import sql_erasure
from drugtime.shared.uow import UnitOfWork

__all__ = ["eraser", "router"]


class _Eraser:
    name = "ai_meal"

    def erase_user(self, uow: UnitOfWork, user_id: UUID) -> None:
        sql_erasure.erase(uow, user_id)


eraser = _Eraser()
