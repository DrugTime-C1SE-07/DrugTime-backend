"""Giao diện công khai của interaction."""

from uuid import UUID

from drugtime.modules.interaction.adapters.inbound.http import router
from drugtime.modules.interaction.adapters.outbound import sql_erasure
from drugtime.shared.uow import UnitOfWork

__all__ = ["eraser", "router"]


class _Eraser:
    name = "interaction"

    def erase_user(self, uow: UnitOfWork, user_id: UUID) -> None:
        sql_erasure.erase(uow, user_id)


eraser = _Eraser()
