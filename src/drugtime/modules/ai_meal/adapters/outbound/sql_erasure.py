from uuid import UUID

from sqlalchemy import text

from drugtime.shared.uow import UnitOfWork


def erase(uow: UnitOfWork, user_id: UUID) -> None:
    uow.connection.execute(text("DELETE FROM meal_suggestions WHERE user_id = :u"), {"u": user_id})
