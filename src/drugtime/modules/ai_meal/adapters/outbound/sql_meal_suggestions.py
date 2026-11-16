import json
from datetime import datetime
from uuid import UUID

from sqlalchemy import text

from drugtime.shared.uow import UnitOfWork


class SqlMealSuggestions:
    """Ghi/đọc `meal_suggestions` (api_role: SELECT, INSERT). Cache CD10 thuộc 5.09."""

    def insert(
        self,
        uow: UnitOfWork,
        user_id: UUID,
        content: dict,
        previous_suggestion_id: int | None = None,
    ) -> tuple[int, datetime]:
        row = uow.connection.execute(
            text(
                "INSERT INTO meal_suggestions "
                "(user_id, suggestion_content, served_from_cache, previous_suggestion_id) "
                "VALUES (:u, CAST(:c AS jsonb), false, :p) RETURNING id, created_at"
            ),
            {
                "u": user_id,
                "c": json.dumps(content, ensure_ascii=False),
                "p": previous_suggestion_id,
            },
        ).one()
        return row.id, row.created_at

    def find_previous(self, uow: UnitOfWork, suggestion_id: int, user_id: UUID) -> dict | None:
        """Chỉ bản ghi của đúng người bệnh; của người khác trả None như không tồn tại (AC16)."""
        row = uow.connection.execute(
            text(
                "SELECT suggestion_content FROM meal_suggestions "
                "WHERE id = :id AND user_id = :u"
            ),
            {"id": suggestion_id, "u": user_id},
        ).one_or_none()
        if row is None or not isinstance(row.suggestion_content, dict):
            return None
        return row.suggestion_content

    def count_refreshes(
        self, uow: UnitOfWork, user_id: UUID, since: datetime, *, lock: bool
    ) -> int:
        if lock:
            # Khóa giao dịch theo user: request gợi ý lại đồng thời chờ tới khi request trước
            # commit/rollback, rồi mới đếm (AC27). Khóa tự nhả khi transaction kết thúc.
            uow.connection.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))"),
                {"k": f"ai_meal_refresh:{user_id}"},
            )
        return uow.connection.execute(
            text(
                "SELECT count(*) FROM meal_suggestions "
                "WHERE user_id = :u AND previous_suggestion_id IS NOT NULL AND created_at >= :s"
            ),
            {"u": user_id, "s": since},
        ).scalar_one()
