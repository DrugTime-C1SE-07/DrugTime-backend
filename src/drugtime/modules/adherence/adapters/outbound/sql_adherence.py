from datetime import datetime
from uuid import UUID

from sqlalchemy import text

from drugtime.modules.adherence.domain.dose import DoseConfirmation
from drugtime.shared.uow import UnitOfWork

# Cài đúng domain.dose.status_after_confirmation: Bỏ lỡ → Uống trễ; không ghi đè taken_at.
_UPSERT_CONFIRMATION = text("""
INSERT INTO dose_logs (medication_schedule_id, scheduled_at, taken_at, status, client_uuid,
                       synced_at)
VALUES (:schedule_id, :scheduled_at, :taken_at, 'Đã uống', :client_uuid, now())
ON CONFLICT (medication_schedule_id, scheduled_at) DO UPDATE SET
    status = CASE WHEN dose_logs.status = 'Bỏ lỡ' THEN 'Uống trễ' ELSE dose_logs.status END,
    taken_at = COALESCE(dose_logs.taken_at, EXCLUDED.taken_at),
    client_uuid = COALESCE(dose_logs.client_uuid, EXCLUDED.client_uuid),
    synced_at = now()
""")

# Cài đúng domain.dose.may_mark_missed: chỉ tạo khi chưa có dòng.
_MARK_MISSED = text("""
INSERT INTO dose_logs (medication_schedule_id, scheduled_at, status)
VALUES (:schedule_id, :scheduled_at, 'Bỏ lỡ')
ON CONFLICT (medication_schedule_id, scheduled_at) DO NOTHING
RETURNING id
""")


class SqlDoseLogs:
    def upsert_confirmation(self, uow: UnitOfWork, c: DoseConfirmation) -> None:
        uow.connection.execute(
            _UPSERT_CONFIRMATION,
            {
                "schedule_id": c.schedule_id,
                "scheduled_at": c.scheduled_at,
                "taken_at": c.taken_at,
                "client_uuid": c.client_uuid,
            },
        )

    def mark_missed(
        self, uow: UnitOfWork, schedule_id: UUID, scheduled_at: datetime
    ) -> UUID | None:
        row = uow.connection.execute(
            _MARK_MISSED, {"schedule_id": schedule_id, "scheduled_at": scheduled_at}
        ).first()
        return None if row is None else row.id

    def erase_for_schedules(self, uow: UnitOfWork, schedule_ids: list[UUID]) -> None:
        if schedule_ids:
            uow.connection.execute(
                text("DELETE FROM dose_logs WHERE medication_schedule_id = ANY(:ids)"),
                {"ids": schedule_ids},
            )


class SqlNotifications:
    def create_missed_alert(
        self, uow: UnitOfWork, recipient_id: UUID, patient_id: UUID, dedupe_key: str
    ) -> UUID | None:
        row = uow.connection.execute(
            text("""
            INSERT INTO notifications (user_id, about_patient_user_id, type, content, is_read,
                                       dedupe_key)
            VALUES (:r, :p, 'canh_bao_bo_lo_lieu_nguoi_than', :content, false, :k)
            ON CONFLICT (dedupe_key) DO NOTHING
            RETURNING id
        """),
            {
                "r": recipient_id,
                "p": patient_id,
                "k": dedupe_key,
                "content": "Chưa ghi nhận liều thuốc đúng giờ",
            },
        ).first()
        return None if row is None else row.id

    def erase_for_user(self, uow: UnitOfWork, user_id: UUID) -> None:
        uow.connection.execute(
            text("DELETE FROM notifications WHERE user_id = :u OR about_patient_user_id = :u"),
            {"u": user_id},
        )


class SqlScanCursor:
    JOB = "missed_dose_scan"

    def get(self, uow: UnitOfWork) -> datetime | None:
        row = uow.connection.execute(
            text("SELECT scanned_until FROM missed_dose_scan_cursor WHERE job_name = :j"),
            {"j": self.JOB},
        ).first()
        return None if row is None else row.scanned_until

    def advance(self, uow: UnitOfWork, until: datetime) -> None:
        uow.connection.execute(
            text("""
            INSERT INTO missed_dose_scan_cursor (job_name, scanned_until, updated_at)
            VALUES (:j, :u, now())
            ON CONFLICT (job_name) DO UPDATE SET scanned_until = EXCLUDED.scanned_until,
                                                 updated_at = now()
        """),
            {"j": self.JOB, "u": until},
        )
