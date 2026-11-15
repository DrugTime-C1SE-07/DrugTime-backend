import json
from datetime import datetime
from uuid import UUID

from sqlalchemy import text

from drugtime.shared.uow import UnitOfWork


class SqlMealSuggestions:
    """Ghi `meal_suggestions` (api_role: SELECT, INSERT). Cache CD10 thuộc 5.09."""

    def insert(self, uow: UnitOfWork, user_id: UUID, content: dict) -> tuple[int, datetime]:
        row = uow.connection.execute(
            text(
                "INSERT INTO meal_suggestions (user_id, suggestion_content, served_from_cache) "
                "VALUES (:u, CAST(:c AS jsonb), false) RETURNING id, created_at"
            ),
            {"u": user_id, "c": json.dumps(content, ensure_ascii=False)},
        ).one()
        return row.id, row.created_at
