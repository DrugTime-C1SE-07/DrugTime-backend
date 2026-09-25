from datetime import datetime
from uuid import UUID

from sqlalchemy import text

from drugtime.modules.medication.domain.schedule import DoseOccurrence
from drugtime.shared.uow import UnitOfWork


class SqlMedication:
    def schedule_owner(self, uow: UnitOfWork, schedule_id: UUID) -> UUID | None:
        row = uow.connection.execute(
            text(
                "SELECT um.user_id FROM medication_schedules ms "
                "JOIN user_medications um ON um.id = ms.user_medication_id WHERE ms.id = :s"
            ),
            {"s": schedule_id},
        ).first()
        return None if row is None else row.user_id

    def schedule_ids_of(self, uow: UnitOfWork, user_id: UUID) -> list[UUID]:
        rows = uow.connection.execute(
            text(
                "SELECT ms.id FROM medication_schedules ms "
                "JOIN user_medications um ON um.id = ms.user_medication_id "
                "WHERE um.user_id = :u"
            ),
            {"u": user_id},
        )
        return [r.id for r in rows]

    def occurrences_between(
        self, uow: UnitOfWork, start: datetime, end: datetime
    ) -> list[DoseOccurrence]:
        """Sinh các lượt uống trong [start, end) từ intake_time + days_of_week (giờ
        Asia/Ho_Chi_Minh), chỉ lấy scheduled_at >= effective_from và reminder_enabled."""
        raise NotImplementedError  # TODO: task missed-dose scan (generate_series theo ngày)

    def erase(self, uow: UnitOfWork, user_id: UUID) -> None:
        c = uow.connection
        c.execute(
            text(
                "DELETE FROM medication_schedules WHERE user_medication_id IN "
                "(SELECT id FROM user_medications WHERE user_id = :u)"
            ),
            {"u": user_id},
        )
        c.execute(text("DELETE FROM user_medications WHERE user_id = :u"), {"u": user_id})
        c.execute(text("DELETE FROM prescriptions WHERE user_id = :u"), {"u": user_id})
        c.execute(text("DELETE FROM user_conditions WHERE user_id = :u"), {"u": user_id})
